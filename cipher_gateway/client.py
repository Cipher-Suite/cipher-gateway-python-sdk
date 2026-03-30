# cipher_gateway/client.py
"""
CipherGateway Python SDK — main client.

Two usage patterns:

  # Pattern 1 — Admin (no auth, for creating users)
  async with CipherGatewayClient.admin(config) as client:
      creds = await client.create_user()

  # Pattern 2 — User (authenticated, for all trading operations)
  async with CipherGatewayClient.for_user(config, api_key="...") as client:
      account = await client.create_account("12345", "password", "ICMarkets-Demo")
      info    = await client.get_account_info()
      pos     = await client.get_positions()
      result  = await client.place_market_buy("EURUSD", volume=0.1)
"""
import asyncio
import logging
import time
from typing import List, Optional

from .models import (
    GatewayConfig,
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
from .exceptions import (
    AccountLoginFailedError,
    AccountNotFoundError,
    AccountTimeoutError,
    CipherGatewayError,
    NotStartedError,
)

logger = logging.getLogger(__name__)


class CipherGatewayClient:
    """
    Python SDK for the Cipher MT5 Gateway.

    Lifecycle:
        client = CipherGatewayClient(config, api_key="...")
        await client.start()
        # ... use client ...
        await client.stop()

    Or as async context manager (preferred):
        async with CipherGatewayClient.for_user(config, api_key="...") as client:
            ...
    """

    def __init__(self, config: GatewayConfig, api_key: Optional[str] = None):
        self._config = config
        self._http = HttpTransport(config)
        self._ws = WebSocketClient(config, api_key=api_key)
        self._started = False

        if api_key:
            self._http.set_api_key(api_key)

    # ==================== Factory methods ====================

    @classmethod
    def admin(cls, config: GatewayConfig) -> 'CipherGatewayClient':
        """
        Create an unauthenticated client for admin operations.
        Used only for: health_check() and create_user().
        """
        return cls(config, api_key=None)

    @classmethod
    def for_user(cls, config: GatewayConfig, api_key: str) -> 'CipherGatewayClient':
        """
        Create an authenticated client for a specific user.
        All trading operations require this.
        """
        return cls(config, api_key=api_key)

    # ==================== Lifecycle ====================

    async def start(self):
        await self._http.start()
        self._started = True
        logger.debug(f"CipherGatewayClient started — {self._config.base_url}")

    async def stop(self):
        await self._ws.disconnect()
        await self._http.stop()
        self._started = False
        logger.debug("CipherGatewayClient stopped")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *_):
        await self.stop()

    # ==================== Health ====================

    async def health_check(self) -> bool:
        """Returns True if gateway is reachable and healthy"""
        try:
            await self._http.get("/health")
            return True
        except Exception:
            return False

    # ==================== User management ====================

    async def create_user(self) -> UserCredentials:
        """
        Create a new gateway user.
        Returns credentials — store gateway_user_id and api_key in your DB.
        No auth required.
        """
        data = await self._http.post("/api/users")
        api_key = data.get('api_key') or data.get('apiKey') or data.get('token', '')
        user_id = data.get('user_id') or data.get('userId', '')

        if not api_key or not user_id:
            raise CipherGatewayError(
                f"create_user() returned incomplete data: {data}"
            )

        logger.info(f"Created gateway user: {user_id}")
        return UserCredentials(
            gateway_user_id=user_id,
            api_key=api_key,
        )

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
        Gateway encrypts credentials — bot never stores them after this call.
        Returns account_id — the only identifier needed for future requests.
        """
        payload = {
            "mt5_login": mt5_login,
            "mt5_password": mt5_password,
            "mt5_server": mt5_server,
        }
        if region:
            payload["region"] = region

        data = await self._http.post("/api/accounts", json=payload)
        account_id = data.get('account_id')

        if not account_id:
            raise CipherGatewayError(
                f"create_account() returned no account_id: {data}"
            )

        logger.info(f"Account provisioned: {account_id}")
        return AccountCredentials(
            account_id=account_id,
            auth_token=data.get('auth_token'),
        )

    async def wait_for_active(
        self,
        account_id: str,
        timeout: int = 60,
        poll_interval: int = 3,
    ) -> None:
        """
        Wait until the account is active (MT5 bridge connected).
        Raises AccountLoginFailedError or AccountTimeoutError on failure.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = await self.get_account_status(account_id)
            state = status.get('status', '')

            if state == 'active':
                logger.info(f"Account {account_id} is active")
                return

            if state in ('login_failed', 'deleted'):
                error = status.get('last_error', 'MT5 login failed')
                raise AccountLoginFailedError(error)

            await asyncio.sleep(poll_interval)

        raise AccountTimeoutError(
            f"Account {account_id} did not become active within {timeout}s"
        )

    async def get_account_status(self, account_id: str) -> dict:
        """Get current status of a provisioned account"""
        return await self._http.get(f"/api/accounts/{account_id}")

    async def get_accounts(self) -> List[dict]:
        """List all accounts for the authenticated user"""
        data = await self._http.get("/api/accounts")
        return data.get('accounts', [])

    async def delete_account(self, account_id: str) -> bool:
        """Deprovision an account — gateway disconnects MT5 and cleans up"""
        await self._http.delete(f"/api/accounts/{account_id}")
        logger.info(f"Account {account_id} deleted")
        return True

    async def pause_account(self, account_id: str) -> bool:
        """Pause trading on an account"""
        await self._http.post(f"/api/accounts/{account_id}/pause")
        return True

    async def resume_account(self, account_id: str) -> bool:
        """Resume trading on a paused account"""
        await self._http.post(f"/api/accounts/{account_id}/resume")
        return True

    # ==================== Account info ====================

    async def get_account_info(self) -> AccountInfo:
        """Get MT5 account balance, equity, margin and other info"""
        data = await self._http.get("/api/account")
        return AccountInfo.from_dict(data.get('account', data))

    # ==================== Positions ====================

    async def get_positions(self) -> List[Position]:
        """Get all open positions"""
        data = await self._http.get("/api/positions")
        return [Position.from_dict(p) for p in data.get('positions', [])]

    async def close_position(self, ticket: int, volume: Optional[float] = None) -> OrderResult:
        """Close an open position by ticket"""
        payload: dict = {"ticket": ticket}
        if volume is not None:
            payload["volume"] = volume
        data = await self._http.post("/api/orders/close", json=payload)
        return OrderResult.from_dict(data)

    async def modify_position(
        self,
        ticket: int,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> OrderResult:
        """Modify stop loss and/or take profit on an open position"""
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
        return await self._place_order(symbol, 'buy', 'market', volume, sl=sl, tp=tp,
                                       comment=comment, magic=magic)

    async def place_market_sell(
        self,
        symbol: str,
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: Optional[str] = None,
        magic: Optional[int] = None,
    ) -> OrderResult:
        return await self._place_order(symbol, 'sell', 'market', volume, sl=sl, tp=tp,
                                       comment=comment, magic=magic)

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
        payload: dict = {
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "volume": volume,
        }
        if price  is not None: payload["price"]   = price
        if sl     is not None: payload["sl"]      = sl
        if tp     is not None: payload["tp"]      = tp
        if comment:            payload["comment"] = comment
        if magic:              payload["magic"]   = magic

        data = await self._http.post("/api/orders", json=payload)
        return OrderResult.from_dict(data)

    # ==================== Market data (REST) ====================

    async def get_symbol_price(self, symbol: str) -> SymbolPrice:
        """
        Get current bid/ask for a symbol.
        Falls back to WebSocket price cache if REST returns zeros.
        """
        try:
            data = await self._http.get(f"/api/symbols/{symbol}")
            price = SymbolPrice.from_dict(symbol, data)
            if price.bid != 0 or price.ask != 0:
                return price
        except Exception as e:
            logger.warning(f"REST price fetch failed for {symbol}: {e}")

        # Fallback — WebSocket price cache
        cached = self._ws.get_cached_price(symbol)
        if cached:
            return SymbolPrice(
                symbol=symbol,
                bid=cached['bid'],
                ask=cached['ask'],
            )

        raise CipherGatewayError(
            f"No price available for {symbol} — "
            "subscribe to ticks or check symbol name"
        )

    # ==================== WebSocket (real-time) ====================

    @property
    def ws(self) -> WebSocketClient:
        """Direct access to WebSocket client for real-time subscriptions"""
        return self._ws

    async def subscribe(self, symbols: List[str], timeframe: Optional[str] = None) -> bool:
        """Subscribe to real-time ticks for the given symbols"""
        return await self._ws.subscribe(symbols, timeframe=timeframe)

    async def unsubscribe(self, symbols: List[str]) -> bool:
        return await self._ws.unsubscribe(symbols)

    async def ping_ws(self) -> bool:
        return await self._ws.ping()
