# tests/test_websocket.py
"""
Layer 2 — WebSocketClient unit tests.
Tests message dispatch, callbacks, and _pending future resolution
without a real WebSocket server.
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tonpo.websocket import WebSocketClient
from tonpo.models import (
    TonpoConfig, Tick, Quote, Candle, Position, OrderResult, AccountInfo
)
from tonpo.exceptions import TonpoConnectionError, SubscriptionError


@pytest.fixture
def ws_client(config):
    return WebSocketClient(config, api_key="sk_test")


# Init and state
class TestWebSocketClientInit:

    def test_initial_state(self, ws_client):
        assert ws_client.connected is False
        assert ws_client._pending == {}
        assert ws_client._price_cache == {}
        assert ws_client._tick_callbacks == {}

    def test_set_api_key(self, ws_client):
        ws_client.set_api_key("new_key")
        assert ws_client._api_key == "new_key"

    def test_get_cached_price_returns_none_when_empty(self, ws_client):
        assert ws_client.get_cached_price("EURUSD") is None

    def test_get_cached_price_returns_data(self, ws_client):
        ws_client._price_cache["EURUSD"] = {"bid": 1.08, "ask": 1.09, "last": 0, "time": 0}
        cached = ws_client.get_cached_price("EURUSD")
        assert cached["bid"] == 1.08


# ==================== Message dispatch ====================

class TestMessageDispatch:

    async def _dispatch(self, ws_client, msg: dict):
        await ws_client._dispatch(json.dumps(msg))

    @pytest.mark.asyncio
    async def test_tick_dispatched_to_callback(self, ws_client):
        received = []
        ws_client.on_tick("EURUSD", lambda t: received.append(t))
        await self._dispatch(ws_client, {
            "type": "tick", "symbol": "EURUSD",
            "bid": 1.0850, "ask": 1.0852, "last": 1.0851, "volume": 10,
            "time": 1712345678
        })
        assert len(received) == 1
        assert isinstance(received[0], Tick)
        assert received[0].symbol == "EURUSD"
        assert received[0].bid    == 1.0850

    @pytest.mark.asyncio
    async def test_tick_updates_price_cache(self, ws_client):
        await self._dispatch(ws_client, {
            "type": "tick", "symbol": "GBPUSD",
            "bid": 1.2700, "ask": 1.2703, "last": 0, "volume": 0,
            "time": 1712345678
        })
        assert ws_client._price_cache["GBPUSD"]["bid"] == 1.2700
        assert ws_client._price_cache["GBPUSD"]["ask"] == 1.2703

    @pytest.mark.asyncio
    async def test_tick_not_dispatched_to_wrong_symbol(self, ws_client):
        received = []
        ws_client.on_tick("EURUSD", lambda t: received.append(t))
        await self._dispatch(ws_client, {
            "type": "tick", "symbol": "GBPUSD",
            "bid": 1.27, "ask": 1.27, "last": 0, "volume": 0, "time": 0
        })
        assert received == []

    @pytest.mark.asyncio
    async def test_quote_dispatched(self, ws_client):
        received = []
        ws_client.on_quote("EURUSD", lambda q: received.append(q))
        await self._dispatch(ws_client, {
            "type": "quote", "symbol": "EURUSD",
            "bid": 1.08, "ask": 1.09, "time": 123
        })
        assert len(received) == 1
        assert isinstance(received[0], Quote)

    @pytest.mark.asyncio
    async def test_candle_dispatched(self, ws_client):
        received = []
        ws_client.on_candle("EURUSD", "H1", lambda c: received.append(c))
        await self._dispatch(ws_client, {
            "type": "candle", "symbol": "EURUSD", "timeframe": "H1",
            "time": 1712340000, "open": 1.08, "high": 1.09, "low": 1.07,
            "close": 1.085, "volume": 1000, "complete": True
        })
        assert len(received) == 1
        assert isinstance(received[0], Candle)
        assert received[0].timeframe == "H1"
        assert received[0].complete is True

    @pytest.mark.asyncio
    async def test_candle_not_dispatched_to_wrong_timeframe(self, ws_client):
        received = []
        ws_client.on_candle("EURUSD", "M1", lambda c: received.append(c))
        await self._dispatch(ws_client, {
            "type": "candle", "symbol": "EURUSD", "timeframe": "H1",
            "time": 0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0, "complete": True
        })
        assert received == []

    @pytest.mark.asyncio
    async def test_position_dispatched(self, ws_client):
        received = []
        ws_client.on_position(lambda p: received.append(p))
        await self._dispatch(ws_client, {
            "type": "position", "ticket": 999, "symbol": "EURUSD", "side": "buy",
            "volume": 0.1, "openPrice": 1.08, "currentPrice": 1.09,
            "profit": 100, "swap": 0, "commission": 0
        })
        assert len(received) == 1
        assert isinstance(received[0], Position)
        assert received[0].ticket == 999

    @pytest.mark.asyncio
    async def test_order_result_dispatched(self, ws_client):
        received = []
        ws_client.on_order_result(lambda r: received.append(r))
        await self._dispatch(ws_client, {
            "type": "orderResult", "ticket": 555, "success": True
        })
        assert len(received) == 1
        assert isinstance(received[0], OrderResult)
        assert received[0].success is True

    @pytest.mark.asyncio
    async def test_account_dispatched(self, ws_client):
        received = []
        ws_client.on_account(lambda a: received.append(a))
        await self._dispatch(ws_client, {
            "type": "account", "login": 12345, "name": "Test",
            "server": "Demo", "balance": 1000, "equity": 1000,
            "margin": 0, "free_margin": 1000, "leverage": 100,
            "currency": "USD", "profit": 0
        })
        assert len(received) == 1
        assert isinstance(received[0], AccountInfo)
        assert received[0].balance == 1000.0

    @pytest.mark.asyncio
    async def test_unknown_message_type_does_not_raise(self, ws_client):
        # Should log and return silently
        await self._dispatch(ws_client, {"type": "unknown_future_type", "data": {}})

    @pytest.mark.asyncio
    async def test_invalid_json_does_not_raise(self, ws_client):
        await ws_client._dispatch("this is not json {{{{")

    @pytest.mark.asyncio
    async def test_pong_resolves_pending_future(self, ws_client):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request_id = "test-req-id-123"
        ws_client._pending[request_id] = future
        await self._dispatch(ws_client, {
            "type": "pong", "request_id": request_id, "timestamp": 999
        })
        assert future.done()
        result = future.result()
        assert result["type"] == "pong"

    @pytest.mark.asyncio
    async def test_subscribed_resolves_pending_future(self, ws_client):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request_id = "sub-req-id"
        ws_client._pending[request_id] = future
        await self._dispatch(ws_client, {
            "type": "subscribed", "request_id": request_id,
            "symbols": ["EURUSD"]
        })
        assert future.done()

    @pytest.mark.asyncio
    async def test_error_rejects_pending_future(self, ws_client):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        request_id = "err-req-id"
        ws_client._pending[request_id] = future
        await self._dispatch(ws_client, {
            "type": "error", "request_id": request_id,
            "code": 400, "message": "Bad request"
        })
        assert future.done()
        assert future.exception() is not None


# ==================== Async vs sync callbacks ====================

class TestCallbackTypes:

    @pytest.mark.asyncio
    async def test_sync_callback_called(self, ws_client):
        received = []
        ws_client.on_tick("EURUSD", lambda t: received.append(t.bid))
        await ws_client._dispatch(json.dumps({
            "type": "tick", "symbol": "EURUSD",
            "bid": 1.11, "ask": 1.12, "last": 0, "volume": 0, "time": 0
        }))
        assert received == [1.11]

    @pytest.mark.asyncio
    async def test_async_callback_called(self, ws_client):
        received = []

        async def async_cb(tick):
            received.append(tick.ask)

        ws_client.on_tick("EURUSD", async_cb)
        await ws_client._dispatch(json.dumps({
            "type": "tick", "symbol": "EURUSD",
            "bid": 1.11, "ask": 1.12, "last": 0, "volume": 0, "time": 0
        }))
        assert received == [1.12]

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_stop_others(self, ws_client):
        results = []

        def bad_cb(t):
            raise RuntimeError("callback crash")

        def good_cb(t):
            results.append(t.bid)

        ws_client.on_tick("EURUSD", bad_cb)
        ws_client.on_tick("EURUSD", good_cb)
        await ws_client._dispatch(json.dumps({
            "type": "tick", "symbol": "EURUSD",
            "bid": 1.11, "ask": 1.12, "last": 0, "volume": 0, "time": 0
        }))
        assert results == [1.11]


# ==================== clear_callbacks ====================

class TestClearCallbacks:

    def test_clear_all(self, ws_client):
        ws_client.on_tick("EURUSD", lambda t: None)
        ws_client.on_quote("EURUSD", lambda q: None)
        ws_client.on_position(lambda p: None)
        ws_client.clear_callbacks()
        assert ws_client._tick_callbacks == {}
        assert ws_client._quote_callbacks == {}
        assert ws_client._position_callbacks == []


# ==================== Multiple callbacks per symbol ====================

class TestMultipleCallbacks:

    @pytest.mark.asyncio
    async def test_multiple_tick_callbacks_all_called(self, ws_client):
        results = []
        ws_client.on_tick("EURUSD", lambda t: results.append("cb1"))
        ws_client.on_tick("EURUSD", lambda t: results.append("cb2"))
        ws_client.on_tick("EURUSD", lambda t: results.append("cb3"))
        await ws_client._dispatch(json.dumps({
            "type": "tick", "symbol": "EURUSD",
            "bid": 1.11, "ask": 1.12, "last": 0, "volume": 0, "time": 0
        }))
        assert results == ["cb1", "cb2", "cb3"]
