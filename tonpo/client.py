# tonpo-py/client.py
"""
Tonpo Python SDK — main client.

Two usage patterns:

  # Admin — no auth, for creating users
  async with TonpoClient.admin(config) as client:
      creds = await client.create_user()

  # User — authenticated, for all trading operations
  async with TonpoClient.for_user(config, api_key="...") as client:
      account = await client.create_account("12345", "password", "ICMarkets-Demo")
      await client.wait_for_active(account.account_id)
      info    = await client.get_account_info()
      pos     = await client.get_positions()
      result  = await client.place_market_buy("EURUSD", volume=0.1)
"""
import asyncio
import logging
import time
from typing import List, Optional

from .models import (
    TonpoConfig,
    UserCredentials,
    AccountCredentials,
    AccountInfo,
    Position,
    OrderResult,
    SymbolPrice,
    Quote,
    Tick,
    Candle,
)
from .transport import HttpTransport
from .websocket import WebSocketClient
38: from .exceptions import (
39:     AccountLoginFailedError,
40:     AccountNotFoundError,
41:     AccountTimeoutError,
42:     NotStartedError,
43: )

logger = logging.getLogger(__name__)


class TonpoClient:
    """
    Python SDK for the Tonpo MT5 Gateway.

    Lifecycle::

        # Preferred — automatic start/stop
        async with TonpoClient.for_user(config, api_key="...") as client:
            await client.get_account_info()

        # Manual
        client = TonpoClient(config, api_key="...")
        await client.start()
        try:
            await client.get_account_info()
        finally:
            await client.stop()
    """

    def __init__(self, config: TonpoConfig, api_key: Optional[str] = None):
        self._config = config
        self._http = HttpTransport(config)
        self._ws   = WebSocketClient(config, api_key=api_key)
        self._started = False

        if api_key:
            self._http.set_api_key(api_key)

    # ==================== Factory methods ====================

    @classmethod
    def admin(cls, config: TonpoConfig) -> 'TonpoClient':
        """
        Create an unauthenticated admin client.
        Use only for: ``health_check()`` and ``create_user()``.
        """
        return cls(config, api_key=None)

    @classmethod
    def for_user(cls, config: TonpoConfig, api_key: str) -> 'TonpoClient':
        """
        Create an authenticated client for a specific user.
        All trading and account operations require this.
        """
        return cls(config, api_key=api_key)

    # ==================== Lifecycle ====================

    async def start(self):
        """Start the HTTP transport. Must be called before any API method."""
        await self._http.start()
        self._started = True
        logger.debug("TonpoClient started — %s", self._config.base_url)

    async def stop(self):
        """Close all connections cleanly."""
        await self._ws.disconnect()
        await self._http.stop()
        self._started = False
        logger.debug("TonpoClient stopped")
    
    def _ensure_started(self) -> None:
        """Raise NotStartedError if client hasn't been started."""
        if not self._started:
            raise NotStartedError(
                "TonpoClient not started. Use 'async with TonpoClient.for_user(config, api_key) as client:' "
                "or call await client.start() before using any methods."
            )

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *_):
        await self.stop()

    # Health 
    async def health_check(self) -> bool:
        """Return True if the gateway is reachable and healthy."""
        self._ensure_started()
        try:
            await self._http.get("/health")
            return True
        except Exception:
            return False

    # User management
    async def create_user(self) -> UserCredentials:
        """
        Create a new Tonpo user. No authentication required.

        Returns a :class:`UserCredentials` with ``gateway_user_id`` and
        ``api_key``. Store both — they are needed for all future requests.
        """
        data = await self._http.post("/api/users")
        api_key = data.get('api_key') or data.get('apiKey') or data.get('token', '')
        user_id = data.get('user_id') or data.get('userId', '')

        if not api_key or not user_id:
            raise TonpoError(
                f"create_user() returned incomplete data: {data}"
            )

        logger.info("Created gateway user: %s", user_id)
        return UserCredentials(gateway_user_id=user_id, api_key=api_key)

    # ==================== Account lifecycle ====================

    async def create_account(
        self,
        mt5_login: str,
        mt5_password: str,
        mt5_server: str,
        region: Optional[str] = None,
    ) -> AccountCredentials:
        """
        Provision an MT5 account on the gateway.

        The gateway encrypts and stores the credentials — you never need to
        store or transmit them again after this call.

        Args:
            mt5_login:    MT5 account number (as a string).
            mt5_password: MT5 account password.
            mt5_server:   Broker server name (e.g. ``"ICMarkets-Demo"``).
            region:       Optional node region (e.g. ``"eu"``).

        Returns:
            :class:`AccountCredentials` with ``account_id``.
            Store ``account_id`` — it identifies this account in all future calls.
        """
        # Gateway CreateAccountRequest uses camelCase (Rust #[serde(rename_all = "camelCase")])
        payload: dict = {
            "mt5Login":    mt5_login,
            "mt5Password": mt5_password,
            "mt5Server":   mt5_server,
        }
        if region:
            payload["region"] = region

        data = await self._http.post("/api/accounts", json=payload)
        account_id = data.get('account_id')

        if not account_id:
            raise TonpoError(
                f"create_account() returned no account_id: {data}"
            )

        logger.info("Account provisioned: %s", account_id)
        return AccountCredentials(
            account_id=account_id,
            auth_token=data.get('auth_token'),
        )

    async def wait_for_active(
        self,
        account_id: str,
        timeout: int = 180,
        poll_interval: int = 5,
    ) -> None:
        """
        Poll until the account reaches ``"active"`` status (MT5 logged in).

        The default timeout is 180 seconds — Windows MT5 cold start takes
        2–4 minutes on a fresh VPS, including Node Agent startup, credential
        fetch, and MT5 initialisation.

        Args:
            account_id:    Account to wait for.
            timeout:       Maximum seconds to wait (default: 180).
            poll_interval: Seconds between status polls (default: 5).

        Raises:
            AccountLoginFailedError: MT5 credentials were rejected by the broker.
            AccountTimeoutError:     Account did not become active in time.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = await self.get_account_status(account_id)
            state  = status.get('status', '')

            if state == 'active':
                logger.info("Account %s is active", account_id)
                return

            if state in ('login_failed', 'deleted'):
                # dict.get(key, default) returns None when the key EXISTS with
                # value None — use 'or' to get the fallback in that case too.
                error = (
                    status.get('last_error')
                    or f"MT5 login failed (account status: {state})"
                )
                raise AccountLoginFailedError(error)

            logger.debug(
                "Account %s status=%s — waiting (%ds remaining)...",
                account_id,
                state,
                int(deadline - time.monotonic()),
            )
            await asyncio.sleep(poll_interval)

        raise AccountTimeoutError(
            f"Account {account_id} did not become active within {timeout}s — "
            "check MT5 credentials, broker server name, and node agent logs"
        )

    async def get_account_status(self, account_id: str) -> dict:
        """
        Get the current status of a provisioned account.

        Returns a dict with at minimum:
          - ``status``     — ``"active"``, ``"connecting"``, ``"login_failed"``, ...
          - ``last_error`` — error string or ``None``
        """
        return await self._http.get(f"/api/accounts/{account_id}")

    async def get_accounts(self) -> List[dict]:
        """List all accounts belonging to the authenticated user."""
        data = await self._http.get("/api/accounts")
        return data.get('accounts', [])

    async def delete_account(self, account_id: str) -> bool:
        """
        Deprovision an account — gateway disconnects MT5 and cleans up the node.
        This is irreversible. You will need to call create_account() again.
        """
        await self._http.delete(f"/api/accounts/{account_id}")
        logger.info("Account %s deleted", account_id)
        return True

    async def pause_account(self, account_id: str) -> bool:
        """Pause trading on an account (keeps MT5 connected, blocks new orders)."""
        await self._http.post(f"/api/accounts/{account_id}/pause")
        return True

    async def resume_account(self, account_id: str) -> bool:
        """Resume a paused account."""
        await self._http.post(f"/api/accounts/{account_id}/resume")
        return True

    # ==================== Account info ====================

    async def get_account_info(self) -> AccountInfo:
        """Get MT5 account balance, equity, margin, and other live info."""
        data = await self._http.get("/api/account")
        return AccountInfo.from_dict(data.get('account', data))
    
    async def list_symbols(self) -> List[str]:
        """
        List all symbols available on the connected MT5 account.
        
        Returns:
            List of symbol strings (e.g. ``["EURUSD", "GBPUSD", "XAUUSD"]``).
        """
        data = await self._http.get("/api/symbols")
        return data.get('symbols', [])

    # ==================== Positions ====================

    async def get_positions(self) -> List[Position]:
        """Get all currently open positions."""
        data = await self._http.get("/api/positions")
        return [Position.from_dict(p) for p in data.get('positions', [])]

    async def close_position(
        self,
        ticket: int,
        volume: Optional[float] = None,
    ) -> OrderResult:
        """
        Close an open position by ticket.
        Args:
            ticket: MT5 position ticket.
            volume: Partial close volume. Omit to close the full position.
        
        Raises:
            TonpoError: If volume is provided and <= 0
        
        """
        # VALIDATION
        if volume is not None and volume < 0:
            raise TonpoError(f"Volume must be positive if provided, got {volume}")
            
        payload: dict = {"ticket": ticket}
        if volume is not None and volume > 0:
            payload["volume"] = volume
        data = await self._http.post("/api/orders/close", json=payload)
        return OrderResult.from_dict(data)

    async def modify_position(
        self,
        ticket: int,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> OrderResult:
        """
        Modify stop-loss and/or take-profit on an open position.
        
        Args:
            ticket: MT5 position ticket.
            sl: New stop loss price (must be positive).
            tp: New take profit price (must be positive).
            
        Raises:
            TonpoError: If sl or tp are provided and <= 0
        """
        if sl is not None and sl <= 0:
            raise TonpoError(f"Stop loss must be positive, got {sl}")
        if tp is not None and tp <= 0:
            raise TonpoError(f"Take profit must be positive, got {tp}")
            
        payload: dict = {"ticket": ticket}
        if sl is not None:
            payload["sl"] = sl
        if tp is not None:
            payload["tp"] = tp
        data = await self._http.post("/api/orders/modify", json=payload)
        return OrderResult.from_dict(data)

    # ==================== Orders ====================

    async def place_market_buy(
        self,
        symbol: str,
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: Optional[str] = None,
        magic: Optional[int] = None,
    ) -> OrderResult:
        """Place a market buy order."""
        return await self._place_order(symbol, 'buy', 'market', volume,
                                       sl=sl, tp=tp, comment=comment, magic=magic)

    async def place_market_sell(
        self,
        symbol: str,
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: Optional[str] = None,
        magic: Optional[int] = None,
    ) -> OrderResult:
        """Place a market sell order."""
        return await self._place_order(symbol, 'sell', 'market', volume,
                                       sl=sl, tp=tp, comment=comment, magic=magic)

    async def place_limit_buy(
        self,
        symbol: str,
        volume: float,
        price: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: Optional[str] = None,
        magic: Optional[int] = None,
    ) -> OrderResult:
        """Place a limit buy order."""
        return await self._place_order(symbol, 'buy', 'limit', volume, price=price,
                                       sl=sl, tp=tp, comment=comment, magic=magic)

    async def place_limit_sell(
        self,
        symbol: str,
        volume: float,
        price: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: Optional[str] = None,
        magic: Optional[int] = None,
    ) -> OrderResult:
        """Place a limit sell order."""
        return await self._place_order(symbol, 'sell', 'limit', volume, price=price,
                                       sl=sl, tp=tp, comment=comment, magic=magic)

    async def place_stop_buy(
        self,
        symbol: str,
        volume: float,
        price: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: Optional[str] = None,
        magic: Optional[int] = None,
    ) -> OrderResult:
        """Place a stop buy order."""
        return await self._place_order(symbol, 'buy', 'stop', volume, price=price,
                                       sl=sl, tp=tp, comment=comment, magic=magic)

    async def place_stop_sell(
        self,
        symbol: str,
        volume: float,
        price: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: Optional[str] = None,
        magic: Optional[int] = None,
    ) -> OrderResult:
        """Place a stop sell order."""
        return await self._place_order(symbol, 'sell', 'stop', volume, price=price,
                                       sl=sl, tp=tp, comment=comment, magic=magic)

    async def _place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        volume: float,
        price: Optional[float] = None,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: Optional[str] = None,
        magic: Optional[int] = None,
    ) -> OrderResult:
        # VOLUME VALIDATION 
        if volume <= 0:
            raise TonpoError(f"Volume must be positive, got {volume}")
        
        #  SYMBOL VALIDATION
        if not symbol or not symbol.strip():
            raise TonpoError("Symbol cannot be empty or whitespace")
        
        # PRICE VALIDATION            
        if order_type in ('limit', 'stop'):
            if price is None:
                raise TonpoError(f"{order_type.capitalize()} orders require a price")
            if price <= 0:
                raise TonpoError(f"Price must be positive for {order_type} orders, got {price}")
        
        #  SL/TP VALIDATION 
        if sl is not None and sl <= 0:
            raise TonpoError(f"Stop loss must be positive, got {sl}")
        if tp is not None and tp <= 0:
            raise TonpoError(f"Take profit must be positive, got {tp}")
            
        payload: dict = {
            "symbol":    symbol,
            "side":      side,
            "orderType": order_type,
            "volume":    volume,
        }
        if price is not None:
            payload["price"] = price
        if sl is not None:
            payload["sl"] = sl
        if tp is not None:
            payload["tp"] = tp
        if comment:
            payload["comment"] = comment
        if magic:
            payload["magic"] = magic

        data = await self._http.post("/api/orders", json=payload)
        return OrderResult.from_dict(data)

    # ==================== Market data (REST) ====================

    async def get_symbol_price(self, symbol: str) -> SymbolPrice:
        """
        Get the current bid/ask for a symbol via REST.
        Falls back to the WebSocket price cache if REST returns zeros.

        Raises:
            TonpoError: No price available (not subscribed, bad symbol).
        """
        try:
            data  = await self._http.get(f"/api/symbols/{symbol}")
            price = SymbolPrice.from_dict(symbol, data)
            if price.bid != 0 or price.ask != 0:
                return price
        except Exception as exc:
            logger.warning("REST price fetch failed for %s: %s", symbol, exc)

        # Fallback — WebSocket price cache populated by subscribe()
        cached = self._ws.get_cached_price(symbol)
        if cached:
            return SymbolPrice(symbol=symbol, bid=cached['bid'], ask=cached['ask'])

        raise TonpoError(
            f"No price available for '{symbol}' — "
            "call subscribe([symbol]) first or check the symbol name"
        )

    # ==================== WebSocket (real-time) ====================

    @property
    def ws(self) -> WebSocketClient:
        """
        Direct access to the :class:`WebSocketClient` for registering
        real-time callbacks (on_tick, on_candle, on_position, etc.).
        """
        return self._ws

    async def subscribe(
        self,
        symbols: List[str],
        timeframe: Optional[str] = None,
    ) -> bool:
        """Subscribe to real-time ticks for the given symbols."""
        return await self._ws.subscribe(symbols, timeframe=timeframe)

    async def unsubscribe(self, symbols: List[str]) -> bool:
        """Unsubscribe from real-time ticks."""
        return await self._ws.unsubscribe(symbols)

    async def ping_ws(self) -> bool:
        """Ping the gateway WebSocket. Returns True on success."""
        return await self._ws.ping()
