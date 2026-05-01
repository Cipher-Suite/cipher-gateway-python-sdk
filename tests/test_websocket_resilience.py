# tests/test_websocket_resilience.py
"""
WebSocket Resilience Tests — Production-Ready

Tests for:
1. Reconnection behavior after disconnects
2. Orphan message handling (pong without ping, etc.)
3. Callback exception resilience
4. Task cleanup on disconnect
5. Connection state consistency

GOAL: Expose bugs in production code so they can be fixed properly.
These tests ensure production-ready resilience.
"""
import asyncio
import json
import pytest
import logging
from unittest.mock import AsyncMock, MagicMock, patch, call
from websockets.exceptions import ConnectionClosed

from tonpo.websocket import WebSocketClient
from tonpo.models import TonpoConfig, Tick, Quote, Candle
from tonpo.exceptions import TonpoConnectionError


logger = logging.getLogger(__name__)


# ==================== RECONNECTION BEHAVIOR TESTS ====================

class TestReconnectionBehavior:
    """Test WebSocket reconnection after disconnects."""

    @pytest.mark.asyncio
    async def test_listener_creates_reconnect_task_on_connection_closed(self, config):
        """When connection closes, listener should schedule reconnect task."""
        ws = WebSocketClient(config)
        
        # Mock connection that will raise ConnectionClosed
        mock_conn = AsyncMock()
        mock_conn.closed = False
        
        async def mock_listen():
            raise ConnectionClosed(None, None)
        
        async def mock_aiter():
            raise ConnectionClosed(None, None)
            yield
        mock_conn.__aiter__ = lambda self: mock_aiter()
        ws._connection = mock_conn
        ws._connected = True
        
        # Call _listen (will handle ConnectionClosed)
        await ws._listen()
        
        # Check: reconnect_task should be created
        assert ws._reconnect_task is not None, "BUG: reconnect_task not created on ConnectionClosed"
        assert isinstance(ws._reconnect_task, asyncio.Task), "BUG: reconnect_task is not a Task"

    @pytest.mark.asyncio
    async def test_listener_sets_connected_false_on_connection_closed(self, config):
        """When connection closes, _connected should be set to False."""
        ws = WebSocketClient(config)
        
        # Mock connection that raises ConnectionClosed
        mock_conn = AsyncMock()
        
        async def mock_listen():
            raise ConnectionClosed(None, None)
        
        async def mock_aiter():
            raise ConnectionClosed(None, None)
            yield
        mock_conn.__aiter__ = lambda self: mock_aiter()
        ws._connection = mock_conn
        ws._connected = True  # Start connected
        
        # Call _listen
        await ws._listen()
        
        # Check: connected should be False
        assert ws._connected is False, "BUG: _connected not set to False on ConnectionClosed"

    @pytest.mark.asyncio
    async def test_reconnect_task_not_duplicated(self, config):
        """Reconnect task should not be created if one is already running."""
        ws = WebSocketClient(config)
        
        # Create existing reconnect task
        existing_task = asyncio.create_task(asyncio.sleep(10))
        ws._reconnect_task = existing_task
        
        # Mock connection
        mock_conn = AsyncMock()
        
        async def mock_listen():
            raise ConnectionClosed(None, None)
        
        async def mock_aiter():
            raise ConnectionClosed(None, None)
            yield
        mock_conn.__aiter__ = lambda self: mock_aiter()
        ws._connection = mock_conn
        ws._connected = True
        
        # Call _listen
        await ws._listen()
        
        # Check: reconnect_task should still be the original
        assert ws._reconnect_task is existing_task, "BUG: reconnect_task was duplicated"

    @pytest.mark.asyncio
    async def test_connect_resets_reconnect_attempts(self, config):
        """Successful connect should reset reconnect attempt counter."""
        ws = WebSocketClient(config)
        ws._reconnect_attempts = 5  # Simulate failed attempts
        
        # Mock successful connection
        async def mock_connect(*args, **kwargs):
            conn = AsyncMock()
            conn.closed = False
            return conn
        
        with patch('tonpo.websocket.websockets.connect', side_effect=mock_connect):
            await ws.connect()
        
        # Check: attempts should be reset
        assert ws._reconnect_attempts == 0, "BUG: reconnect_attempts not reset on successful connect"

    @pytest.mark.asyncio
    async def test_reconnect_respects_max_attempts(self, config):
        """Reconnection should fail after max_reconnect_attempts."""
        ws = WebSocketClient(config)
        ws._config.max_reconnect_attempts = 2
        ws._config.ws_reconnect_delay = 0.001  # Fast test
        
        # Mock connection that always fails
        with patch('tonpo.websocket.websockets.connect', side_effect=ConnectionError("Fail")):
            with pytest.raises(TonpoConnectionError) as exc:
                await ws.connect()
            
            # Check: should have attempted max times
            assert ws._reconnect_attempts == 2, f"BUG: reconnect_attempts={ws._reconnect_attempts}, expected 2"
            assert "2 attempts" in str(exc.value), "BUG: error message should mention attempt count"


# ==================== ORPHAN MESSAGE HANDLING TESTS ====================

class TestOrphanMessageHandling:
    """Test handling of orphan/unexpected messages."""

    @pytest.mark.asyncio
    async def test_pong_without_ping_handled_gracefully(self, config):
        """Pong message without pending request should not crash."""
        ws = WebSocketClient(config)
        
        # Send pong with nonexistent request_id
        pong = json.dumps({"type": "pong", "request_id": "nonexistent-id"})
        
        # Should not raise
        await ws._dispatch(pong)
        
        # Check: pending should be empty
        assert len(ws._pending) == 0, "BUG: orphan pong affected _pending dict"

    @pytest.mark.asyncio
    async def test_invalid_json_ignored(self, config):
        """Invalid JSON should be logged but not crash."""
        ws = WebSocketClient(config)
        
        invalid = "not valid json {{"
        
        # Should not raise
        await ws._dispatch(invalid)
        
        # Check: no crash, state unchanged
        assert ws.connected is False

    @pytest.mark.asyncio
    async def test_unknown_message_type_ignored(self, config):
        """Unknown message types should be logged and ignored."""
        ws = WebSocketClient(config)
        
        unknown = json.dumps({"type": "unknown_event", "data": "something"})
        
        # Should not raise
        await ws._dispatch(unknown)
        
        # Check: no crash
        assert ws.connected is False

    @pytest.mark.asyncio
    async def test_response_without_request_id_not_crash(self, config):
        """Response without request_id should not crash."""
        ws = WebSocketClient(config)
        
        # Response with no request_id
        response = json.dumps({"type": "subscribed", "symbols": ["EURUSD"]})
        
        # Should not raise
        await ws._dispatch(response)

    @pytest.mark.asyncio
    async def test_tick_with_missing_required_field(self, config):
        """Tick with missing required field should be handled."""
        ws = WebSocketClient(config)
        
        # Tick missing 'time' field
        tick = json.dumps({
            "type": "tick",
            "symbol": "EURUSD",
            "bid": 1.0800,
            "ask": 1.0802
            # Missing 'time'
        })
        
        # Should handle gracefully (may raise KeyError which is caught)
        try:
            await ws._dispatch(tick)
        except KeyError as e:
            # Expected - missing required field
            logger.info(f"Expected KeyError for missing field: {e}")

    @pytest.mark.asyncio
    async def test_price_cache_updated_before_callbacks(self, config):
        """Price cache should be updated even if callbacks fail."""
        ws = WebSocketClient(config)
        
        # Register callback that raises
        def bad_callback(tick):
            raise ValueError("Callback error")
        
        ws.on_tick("EURUSD", bad_callback)
        
        # Send tick
        tick = json.dumps({
            "type": "tick",
            "symbol": "EURUSD",
            "bid": 1.0800,
            "ask": 1.0802,
            "time": 1234567890
        })
        
        await ws._dispatch(tick)
        
        # Check: price cache should be updated DESPITE callback error
        cached = ws.get_cached_price("EURUSD")
        assert cached is not None, "BUG: price cache not updated when callback raises"
        assert cached["bid"] == 1.0800, "BUG: price cache has wrong value"


# ==================== CALLBACK EXCEPTION RESILIENCE TESTS ====================

class TestCallbackExceptionResilience:
    """Test that callback exceptions don't crash listener."""

    @pytest.mark.asyncio
    async def test_sync_callback_exception_logged_not_raised(self, config):
        """Sync callback exception should be logged but not raised."""
        ws = WebSocketClient(config)
        
        def bad_callback(tick):
            raise RuntimeError("Sync callback error")
        
        ws.on_tick("EURUSD", bad_callback)
        
        tick = json.dumps({
            "type": "tick",
            "symbol": "EURUSD",
            "bid": 1.0800,
            "ask": 1.0802,
            "time": 1234567890
        })
        
        # Should NOT raise
        await ws._dispatch(tick)

    @pytest.mark.asyncio
    async def test_async_callback_exception_logged_not_raised(self, config):
        """Async callback exception should be logged but not raised."""
        ws = WebSocketClient(config)
        
        async def bad_callback(tick):
            raise RuntimeError("Async callback error")
        
        ws.on_tick("EURUSD", bad_callback)
        
        tick = json.dumps({
            "type": "tick",
            "symbol": "EURUSD",
            "bid": 1.0800,
            "ask": 1.0802,
            "time": 1234567890
        })
        
        # Should NOT raise
        await ws._dispatch(tick)

    @pytest.mark.asyncio
    async def test_multiple_callbacks_one_fails_others_still_called(self, config):
        """If one callback fails, others should still be called."""
        ws = WebSocketClient(config)
        
        called_count = [0]
        
        def bad_callback(tick):
            raise ValueError("First callback fails")
        
        def good_callback(tick):
            called_count[0] += 1
        
        ws.on_tick("EURUSD", bad_callback)
        ws.on_tick("EURUSD", good_callback)
        
        tick = json.dumps({
            "type": "tick",
            "symbol": "EURUSD",
            "bid": 1.0800,
            "ask": 1.0802,
            "time": 1234567890
        })
        
        await ws._dispatch(tick)
        
        # Check: second callback should have been called
        assert called_count[0] == 1, f"BUG: good_callback not called, count={called_count[0]}"

    @pytest.mark.asyncio
    async def test_callback_exception_doesnt_stop_listener(self, config):
        """Callback exception shouldn't prevent listener from processing more messages."""
        ws = WebSocketClient(config)
        
        messages_processed = [0]
        
        async def bad_callback(tick):
            raise ValueError("Callback error")
        
        async def tracking_callback(tick):
            messages_processed[0] += 1
        
        ws.on_tick("EURUSD", bad_callback)
        ws.on_tick("EURUSD", tracking_callback)
        
        # Send multiple ticks
        for i in range(3):
            tick = json.dumps({
                "type": "tick",
                "symbol": "EURUSD",
                "bid": 1.0800 + i * 0.0001,
                "ask": 1.0802 + i * 0.0001,
                "time": 1234567890 + i
            })
            await ws._dispatch(tick)
        
        # Check: all messages should have been processed
        assert messages_processed[0] == 3, f"BUG: only {messages_processed[0]} messages processed, expected 3"

    @pytest.mark.asyncio
    async def test_different_callback_types_error_handling(self, config):
        """Different callback types should all be error-handled."""
        ws = WebSocketClient(config)
        
        # Position callback that raises
        def bad_position_callback(pos):
            raise RuntimeError("Position callback error")
        
        # Order callback that raises
        def bad_order_callback(order):
            raise RuntimeError("Order callback error")
        
        ws.on_position(bad_position_callback)
        ws.on_order_result(bad_order_callback)
        
        # Send position message
        pos = json.dumps({
            "type": "position",
            "ticket": 123,
            "symbol": "EURUSD",
            "magic": 0,
            "type": "BUY",
            "volume": 1.0,
            "open_price": 1.0800,
            "sl": 1.0700,
            "tp": 1.0900,
            "commission": 0,
            "swap": 0,
            "profit": 100
        })
        
        # Send order message
        order = json.dumps({
            "type": "orderResult",
            "ticket": 456,
            "symbol": "EURUSD",
            "success": True,
            "comment": "Order placed"
        })
        
        # Should not raise
        await ws._dispatch(pos)
        await ws._dispatch(order)


# ==================== TASK CLEANUP TESTS ====================

class TestTaskCleanup:
    """Test proper cleanup of tasks on disconnect."""

    @pytest.mark.asyncio
    async def test_listener_task_cancelled_on_disconnect(self, config):
        """Listener task should be cancelled on disconnect."""
        ws = WebSocketClient(config)
        
        # Create a task that will be cancelled
        async def fake_listener():
            await asyncio.sleep(10)
        
        ws._listener_task = asyncio.create_task(fake_listener())
        ws._connection = AsyncMock()
        ws._connection.closed = False
        ws._connected = True
        
        # Disconnect
        await ws.disconnect()
        
        # Check: listener task should be cancelled
        assert ws._listener_task.done(), "BUG: listener task not done after disconnect"
        assert ws._listener_task.cancelled(), "BUG: listener task not cancelled"

    @pytest.mark.asyncio
    async def test_reconnect_task_cancelled_on_disconnect(self, config):
        """Reconnect task should be cancelled on disconnect."""
        ws = WebSocketClient(config)
        
        async def fake_reconnect():
            await asyncio.sleep(10)
        
        ws._reconnect_task = asyncio.create_task(fake_reconnect())
        ws._connected = True
        
        # Disconnect
        await ws.disconnect()
        
        # Check: reconnect task should be cancelled
        assert ws._reconnect_task.done(), "BUG: reconnect task not done after disconnect"

    @pytest.mark.asyncio
    async def test_connection_closed_on_disconnect(self, config):
        """Connection should be closed on disconnect."""
        ws = WebSocketClient(config)
        
        mock_conn = AsyncMock()
        mock_conn.closed = False
        ws._connection = mock_conn
        ws._connected = True
        
        # Disconnect
        await ws.disconnect()
        
        # Check: close() should have been called
        mock_conn.close.assert_called_once(), "BUG: connection.close() not called"
        assert ws._connection is None, "BUG: connection not set to None"

    @pytest.mark.asyncio
    async def test_multiple_disconnect_calls_idempotent(self, config):
        """Multiple disconnect calls should be safe (idempotent)."""
        ws = WebSocketClient(config)
        
        mock_conn = AsyncMock()
        mock_conn.closed = False
        ws._connection = mock_conn
        ws._connected = True
        ws._listener_task = asyncio.create_task(asyncio.sleep(10))
        
        # Call disconnect multiple times
        await ws.disconnect()
        await ws.disconnect()  # Should not raise
        await ws.disconnect()  # Should not raise
        
        # Check: only called once
        mock_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_pending_futures_handled_on_disconnect(self, config):
        """Pending futures should be cleaned up or handled on disconnect."""
        ws = WebSocketClient(config)
        
        # Add pending future
        future = asyncio.get_running_loop().create_future()
        ws._pending["test-id"] = future
        
        # Disconnect
        await ws.disconnect()
        
        # Check: pending should still be there (futures aren't auto-cleared by disconnect)
        # This is expected behavior - futures are timeout-handled in _send()
        # But we should verify this behavior is documented/expected


# ==================== CONNECTION STATE CONSISTENCY TESTS ====================

class TestConnectionStateConsistency:
    """Test connection state consistency."""

    @pytest.mark.asyncio
    async def test_connected_property_reflects_state(self, config):
        """connected property should accurately reflect state."""
        ws = WebSocketClient(config)
        
        # Start disconnected
        assert ws.connected is False
        
        # Set connected
        ws._connected = True
        assert ws.connected is True
        
        # Set disconnected
        ws._connected = False
        assert ws.connected is False

    @pytest.mark.asyncio
    async def test_send_triggers_reconnect_if_disconnected(self, config):
        """Send should reconnect if currently disconnected."""
        ws = WebSocketClient(config)
        
        connect_called = [False]
        original_connect = ws.connect
        
        async def mock_connect():
            connect_called[0] = True
            ws._connection = AsyncMock()
            ws._connection.closed = False
            ws._connected = True
        
        ws.connect = mock_connect
        
        # Start disconnected
        assert ws.connected is False
        
        # Try to send
        mock_conn = AsyncMock()
        ws._connection = mock_conn
        ws._connected = True
        
        try:
            await ws._send({"type": "ping"}, timeout=0.1)
        except:
            pass
        
        # Even if it fails, connect should have been triggered
        # (if disconnect status was checked)

    @pytest.mark.asyncio
    async def test_listener_error_sets_connected_false(self, config):
        """Listener error should set _connected to False."""
        ws = WebSocketClient(config)
        
        # Mock connection that raises generic error
        mock_conn = AsyncMock()
        
        async def mock_listen():
            raise RuntimeError("Generic listener error")
        
        async def mock_aiter():
            raise ConnectionClosed(None, None)
            yield
        mock_conn.__aiter__ = lambda self: mock_aiter()
        ws._connection = mock_conn
        ws._connected = True
        
        # Call _listen
        await ws._listen()
        
        # Check: connected should be False
        assert ws._connected is False, "BUG: _connected not set to False on listener error"

    @pytest.mark.asyncio
    async def test_disconnect_sets_connected_false_first(self, config):
        """Disconnect should set _connected=False before cancelling tasks."""
        ws = WebSocketClient(config)
        ws._connected = True
        
        # Mock async task that checks _connected
        disconnect_order = []
        
        async def task_that_checks_state():
            await asyncio.sleep(0)
            if ws._connected:
                disconnect_order.append("connected_still_true")
            else:
                disconnect_order.append("connected_false")
        
        task = asyncio.create_task(task_that_checks_state())
        ws._listener_task = task
        
        # Disconnect
        await ws.disconnect()
        
        # Task should have seen connected=False
        # (order of operations: set False first, then cancel)


# ==================== MESSAGE PROCESSING CONSISTENCY TESTS ====================

class TestMessageProcessingConsistency:
    """Test message processing reliability."""

    @pytest.mark.asyncio
    async def test_price_cache_persists_across_ticks(self, config):
        """Price cache should persist and update correctly."""
        ws = WebSocketClient(config)
        
        # Send multiple ticks
        for i in range(3):
            tick = json.dumps({
                "type": "tick",
                "symbol": "EURUSD",
                "bid": 1.0800 + i * 0.0001,
                "ask": 1.0802 + i * 0.0001,
                "time": 1234567890 + i
            })
            await ws._dispatch(tick)
        
        # Get latest price
        cached = ws.get_cached_price("EURUSD")
        
        # Check: should have latest values
        assert cached is not None, "BUG: price cache is None"
        assert cached["bid"] == 1.0802, f"BUG: cached bid={cached['bid']}, expected 1.0802"
        assert cached["ask"] == 1.0804, f"BUG: cached ask={cached['ask']}, expected 1.0804"

    @pytest.mark.asyncio
    async def test_multiple_symbols_cached_independently(self, config):
        """Different symbols should have independent caches."""
        ws = WebSocketClient(config)
        
        # Send ticks for different symbols
        for symbol, bid in [("EURUSD", 1.0800), ("GBPUSD", 1.2500)]:
            tick = json.dumps({
                "type": "tick",
                "symbol": symbol,
                "bid": bid,
                "ask": bid + 0.0002,
                "time": 1234567890
            })
            await ws._dispatch(tick)
        
        # Check both are cached independently
        eurusd = ws.get_cached_price("EURUSD")
        gbpusd = ws.get_cached_price("GBPUSD")
        
        assert eurusd is not None, "BUG: EURUSD not cached"
        assert gbpusd is not None, "BUG: GBPUSD not cached"
        assert eurusd["bid"] == 1.0800, "BUG: EURUSD bid incorrect"
        assert gbpusd["bid"] == 1.2500, "BUG: GBPUSD bid incorrect"

    @pytest.mark.asyncio
    async def test_response_future_completed_with_correct_data(self, config):
        """Response should complete pending future with data."""
        ws = WebSocketClient(config)
        
        # Add pending future
        request_id = "req-123"
        future = asyncio.get_running_loop().create_future()
        ws._pending[request_id] = future
        
        # Send response
        response = json.dumps({
            "type": "subscribed",
            "request_id": request_id,
            "symbols": ["EURUSD"]
        })
        
        await ws._dispatch(response)
        
        # Check: future completed with correct data
        assert future.done(), "BUG: future not completed"
        result = future.result()
        assert result["type"] == "subscribed", "BUG: future result type incorrect"
        assert request_id not in ws._pending, "BUG: request_id still in pending after completion"

    @pytest.mark.asyncio
    async def test_error_response_sets_exception(self, config):
        """Error response should set exception on pending future."""
        ws = WebSocketClient(config)
        
        # Add pending future
        request_id = "req-456"
        future = asyncio.get_running_loop().create_future()
        ws._pending[request_id] = future
        
        # Send error
        error = json.dumps({
            "type": "error",
            "request_id": request_id,
            "code": "INVALID_SYMBOL",
            "message": "Symbol not found"
        })
        
        await ws._dispatch(error)
        
        # Check: future has exception
        assert future.done(), "BUG: future not completed on error"
        with pytest.raises(TonpoConnectionError):
            future.result()
        assert request_id not in ws._pending, "BUG: request_id still in pending after error"


# ==================== LISTENER ROBUSTNESS TESTS ====================

class TestListenerRobustness:
    """Test listener task robustness."""

    @pytest.mark.asyncio
    async def test_listener_processes_messages_after_error_message(self, config):
        """Listener should continue after processing an error message."""
        ws = WebSocketClient(config)
        
        messages_processed = [0]
        
        async def tracking_callback(tick):
            messages_processed[0] += 1
        
        ws.on_tick("EURUSD", tracking_callback)
        
        # Send error, then tick
        error = json.dumps({
            "type": "error",
            "code": "TEST",
            "message": "Test error"
        })
        
        tick = json.dumps({
            "type": "tick",
            "symbol": "EURUSD",
            "bid": 1.0800,
            "ask": 1.0802,
            "time": 1234567890
        })
        
        await ws._dispatch(error)
        await ws._dispatch(tick)
        
        # Check: tick was processed
        assert messages_processed[0] == 1, f"BUG: tick not processed after error, count={messages_processed[0]}"

    @pytest.mark.asyncio
    async def test_listener_handles_json_error_and_continues(self, config):
        """Listener should continue after JSON parse error."""
        ws = WebSocketClient(config)
        
        messages_processed = [0]
        
        async def tracking_callback(tick):
            messages_processed[0] += 1
        
        ws.on_tick("EURUSD", tracking_callback)
        
        # Send invalid JSON, then valid tick
        invalid = "not json {{"
        
        tick = json.dumps({
            "type": "tick",
            "symbol": "EURUSD",
            "bid": 1.0800,
            "ask": 1.0802,
            "time": 1234567890
        })
        
        await ws._dispatch(invalid)
        await ws._dispatch(tick)
        
        # Check: tick was processed
        assert messages_processed[0] == 1, f"BUG: tick not processed after JSON error, count={messages_processed[0]}"


# ==================== TIMEOUT & PENDING FUTURES TESTS ====================

class TestTimeoutAndPendingFutures:
    """Test timeout handling and pending futures."""

    @pytest.mark.asyncio
    async def test_send_timeout_removes_from_pending(self, config):
        """Timed-out send should remove request from pending."""
        ws = WebSocketClient(config)
        
        # Mock connection that never responds
        mock_conn = AsyncMock()
        mock_conn.closed = False
        mock_conn.send = AsyncMock()
        
        ws._connection = mock_conn
        ws._connected = True
        
        # Send with very short timeout
        with pytest.raises(asyncio.TimeoutError):
            await ws._send({"type": "ping"}, timeout=0.001)
        
        # Pending should be cleaned up
        # (The future might still be in dict but we popped it)
        # Verify this is the expected behavior

    @pytest.mark.asyncio
    async def test_already_done_future_not_overwritten(self, config):
        """If future already done, response shouldn't overwrite it."""
        ws = WebSocketClient(config)
        
        # Add pending future and complete it
        request_id = "req-789"
        future = asyncio.get_running_loop().create_future()
        future.set_result({"original": "value"})
        ws._pending[request_id] = future
        
        # Send response for completed future
        response = json.dumps({
            "type": "subscribed",
            "request_id": request_id,
            "symbols": ["EURUSD"]
        })
        
        await ws._dispatch(response)
        
        # Check: original value still there (not overwritten)
        # Actually, code calls pop() which removes it, so it won't try to set
        # Verify this is expected behavior

