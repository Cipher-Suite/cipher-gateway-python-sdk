# tonpo-py/websocket.py
"""
WebSocket layer for real-time market data and account events.
Manages persistent connection, auto-reconnection, and callback dispatch.
"""
import asyncio
import json
import logging
import uuid
from typing import Callable, Dict, List, Optional, Any

import websockets
from websockets.exceptions import ConnectionClosed

from .exceptions import TonpoConnectionError, SubscriptionError
from .models import (
    AccountInfo,
    Candle,
    OrderResult,
    Position,
    Quote,
    Tick,
    TonpoConfig,
)

logger = logging.getLogger(__name__)


class WebSocketClient:
    """
    Persistent WebSocket connection to the gateway.
    Handles reconnection, message routing, and callback registration.

    Not used directly — access via TonpoClient.ws or subscribe().
    """

    def __init__(self, config: TonpoConfig, api_key: Optional[str] = None):
        self._config = config
        self._api_key = api_key
        self._connection: Optional[websockets.WebSocketClientProtocol] = None
        self._listener_task: Optional[asyncio.Task] = None
        self._reconnect_task: Optional[asyncio.Task] = None
        self._reconnect_attempts = 0
        self._connected = False

        # Pending request futures — keyed by request_id
        self._pending: Dict[str, asyncio.Future] = {}

        # Price cache — updated by incoming ticks; read by get_symbol_price()
        self._price_cache: Dict[str, Dict[str, float]] = {}

        # Callbacks
        self._tick_callbacks:     Dict[str, List[Callable]] = {}
        self._quote_callbacks:    Dict[str, List[Callable]] = {}
        self._candle_callbacks:   Dict[str, List[Callable]] = {}
        self._position_callbacks: List[Callable] = []
        self._order_callbacks:    List[Callable] = []
        self._account_callbacks:  List[Callable] = []

    def set_api_key(self, api_key: str):
        self._api_key = api_key

    @property
    def connected(self) -> bool:
        return self._connected

    def get_cached_price(self, symbol: str) -> Optional[Dict[str, float]]:
        """Return the most recent tick prices for a symbol, or None."""
        return self._price_cache.get(symbol)

    # ==================== Connection ====================

    async def connect(self):
        """Connect WebSocket. No-op if already connected."""
        if self._connection and not self._connection.closed:
            return
        self._reconnect_attempts = 0
        await self._connect_with_retry()

    async def disconnect(self):
        """Close WebSocket cleanly and cancel background tasks."""
        self._connected = False

        for task in (self._reconnect_task, self._listener_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass  # Expected when cancelling
                except Exception as exc:
                    logger.warning("Error during task cleanup: %s", exc)

        if self._connection and not self._connection.closed:
            await self._connection.close()
            self._connection = None

    async def _connect_with_retry(self):
        headers = {}
        if self._api_key:
            headers[self._config.api_key_header] = self._api_key

        while self._reconnect_attempts < self._config.max_reconnect_attempts:
            try:
                self._connection = await websockets.connect(
                    self._config.ws_url,
                    extra_headers=headers,
                    open_timeout=self._config.connect_timeout,
                )
                self._connected = True
                self._reconnect_attempts = 0
                logger.info("WebSocket connected to %s", self._config.ws_url)
                self._listener_task = asyncio.create_task(self._listen())
                return
            except Exception as exc:
                self._reconnect_attempts += 1
                logger.warning(
                    "WebSocket connect failed (attempt %d/%d): %s",
                    self._reconnect_attempts,
                    self._config.max_reconnect_attempts,
                    exc,
                )
                if self._reconnect_attempts < self._config.max_reconnect_attempts:
                    await asyncio.sleep(self._config.ws_reconnect_delay)
                else:
                    raise TonpoConnectionError(
                        f"WebSocket connection failed after "
                        f"{self._config.max_reconnect_attempts} attempts"
                    ) from exc

    async def _listen(self):
        try:
            async for message in self._connection:
                await self._dispatch(message)
        except ConnectionClosed as exc:
            try:
                msg = str(exc)
                logger.warning("WebSocket closed (%s) — scheduling reconnect", msg)
            except Exception:
                logger.warning("WebSocket closed — scheduling reconnect")
                
            self._connected = False
            if not self._reconnect_task or self._reconnect_task.done():
                self._reconnect_task = asyncio.create_task(
                    self._connect_with_retry()
                )
        except Exception as exc:
            logger.error("WebSocket listener error: %s", exc)
            self._connected = False

    # ==================== Message dispatch ====================

    async def _dispatch(self, raw: str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.error("Invalid JSON from gateway: %.100s", raw)
            return

        msg_type = data.get('type')
        handlers = {
            'tick':         self._on_tick,
            'quote':        self._on_quote,
            'candle':       self._on_candle,
            'position':     self._on_position,
            'orderResult':  self._on_order_result,
            'account':      self._on_account,
            'pong':         self._on_pong,
            'subscribed':   self._on_response,
            'unsubscribed': self._on_response,
            'positions':    self._on_response,
            'error':        self._on_error,
        }
        handler = handlers.get(msg_type)
        if handler:
            try:
                await handler(data)
            except Exception as exc:
                logger.error("Handler error for '%s': %s", msg_type, exc)
        else:
            logger.debug("Unknown WS message type: %s", msg_type)

    async def _on_tick(self, data: dict):
        tick = Tick(
            symbol=data['symbol'],
            bid=float(data['bid']),
            ask=float(data['ask']),
            last=float(data.get('last', 0)),
            volume=int(data.get('volume', 0)),
            time=int(data['time']),
        )
        self._price_cache[tick.symbol] = {
            'bid': tick.bid, 'ask': tick.ask,
            'last': tick.last, 'time': tick.time,
        }
        for cb in self._tick_callbacks.get(tick.symbol, []):
            await self._call(cb, tick)

    async def _on_quote(self, data: dict):
        quote = Quote(
            symbol=data['symbol'],
            bid=float(data['bid']),
            ask=float(data['ask']),
            time=int(data['time']),
        )
        for cb in self._quote_callbacks.get(quote.symbol, []):
            await self._call(cb, quote)

    async def _on_candle(self, data: dict):
        candle = Candle(
            symbol=data['symbol'],
            timeframe=data['timeframe'],
            time=int(data['time']),
            open=float(data['open']),
            high=float(data['high']),
            low=float(data['low']),
            close=float(data['close']),
            volume=int(data['volume']),
            complete=bool(data['complete']),
        )
        key = f"{candle.symbol}:{candle.timeframe}"
        for cb in self._candle_callbacks.get(key, []):
            await self._call(cb, candle)

    async def _on_position(self, data: dict):
        position = Position.from_dict(data)
        for cb in self._position_callbacks:
            await self._call(cb, position)

    async def _on_order_result(self, data: dict):
        result = OrderResult.from_dict(data)
        for cb in self._order_callbacks:
            await self._call(cb, result)

    async def _on_account(self, data: dict):
        account = AccountInfo.from_dict(data)
        for cb in self._account_callbacks:
            await self._call(cb, account)

    async def _on_pong(self, data: dict):
        await self._on_response(data)

    async def _on_response(self, data: dict):
        request_id = data.get('request_id')
        if request_id and request_id in self._pending:
            future = self._pending.pop(request_id)
            if not future.done():
                future.set_result(data)

    async def _on_error(self, data: dict):
        code = data.get('code')
        msg  = data.get('message', 'Tonpo error')
        logger.error("Tonpo WS error %s: %s", code, msg)
        request_id = data.get('request_id')
        if request_id and request_id in self._pending:
            future = self._pending.pop(request_id)
            if not future.done():
                future.set_exception(TonpoConnectionError(msg))

    @staticmethod
    async def _call(cb: Callable, arg: Any):
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb(arg)
            else:
                cb(arg)
        except Exception as exc:
            logger.error("Callback error: %s", exc)

    # ==================== Commands ====================

    async def _send(self, payload: dict, timeout: float = 5.0) -> dict:
        if not self._connected or not self._connection:
            await self.connect()

        request_id = str(uuid.uuid4())
        payload['request_id'] = request_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        await self._connection.send(json.dumps(payload))

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise

    async def subscribe(
        self,
        symbols: List[str],
        timeframe: Optional[str] = None,
    ) -> bool:
        """Subscribe to real-time market data for the given symbols."""
        payload: dict = {"type": "subscribe", "symbols": symbols}
        if timeframe:
            payload["timeframe"] = timeframe
        try:
            response = await self._send(payload)
            return response.get('type') == 'subscribed'
        except asyncio.TimeoutError:
            raise SubscriptionError(f"Subscription timeout for {symbols}")

    async def unsubscribe(self, symbols: List[str]) -> bool:
        if not self._connected:
            return False
        try:
            response = await self._send({"type": "unsubscribe", "symbols": symbols})
            return response.get('type') == 'unsubscribed'
        except asyncio.TimeoutError:
            return False

    async def ping(self) -> bool:
        """Ping the gateway WebSocket. Raises TonpoConnectionError on timeout."""
        try:
            await self._send({"type": "ping"}, timeout=5.0)
            return True
        except asyncio.TimeoutError:
            raise TonpoConnectionError("Ping timeout — gateway unreachable")

    async def get_positions_ws(self) -> List[Position]:
        """Get open positions via WebSocket (async)."""
        try:
            response = await self._send({"type": "getPositions"})
            if response.get('type') == 'positions':
                return [Position.from_dict(p) for p in response.get('positions', [])]
        except asyncio.TimeoutError:
            pass
        return []

    # ==================== Callback registration ====================

    def on_tick(self, symbol: str, callback: Callable[[Tick], Any]):
        """Register a callback for real-time tick updates on a symbol."""
        self._tick_callbacks.setdefault(symbol, []).append(callback)

    def on_quote(self, symbol: str, callback: Callable[[Quote], Any]):
        """Register a callback for bid/ask quote updates on a symbol."""
        self._quote_callbacks.setdefault(symbol, []).append(callback)

    def on_candle(self, symbol: str, timeframe: str, callback: Callable[[Candle], Any]):
        """Register a callback for candle updates on a symbol+timeframe pair."""
        self._candle_callbacks.setdefault(f"{symbol}:{timeframe}", []).append(callback)

    def on_position(self, callback: Callable[[Position], Any]):
        """Register a callback for position updates."""
        self._position_callbacks.append(callback)

    def on_order_result(self, callback: Callable[[OrderResult], Any]):
        """Register a callback for order execution results."""
        self._order_callbacks.append(callback)

    def on_account(self, callback: Callable[[AccountInfo], Any]):
        """Register a callback for account balance/equity updates."""
        self._account_callbacks.append(callback)

    def clear_callbacks(self):
        """Remove all registered callbacks."""
        self._tick_callbacks.clear()
        self._quote_callbacks.clear()
        self._candle_callbacks.clear()
        self._position_callbacks.clear()
        self._order_callbacks.clear()
        self._account_callbacks.clear()
