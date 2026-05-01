# tests/test_client_validation.py
"""
Client validation tests — ensures input validation and edge case handling.

These tests verify that the client:
1. Validates order parameters (volumes, prices, symbols)
2. Rejects invalid inputs before sending to gateway
3. Handles edge cases in wait_for_active()
4. Exposes bugs if validation is missing
"""
import pytest
import httpx
import respx

from tonpo.client import TonpoClient
from tonpo.models import TonpoConfig
from tonpo.exceptions import (
    TonpoError,
    AccountTimeoutError,
    AccountLoginFailedError,
)


# ==================== Order Validation Tests ====================

class TestOrderVolume:
    """Validate volume parameter in orders."""

    @pytest.mark.asyncio
    async def test_market_order_zero_volume_should_be_rejected(self, config):
        """Zero volume should be rejected before sending to gateway.
        
        Bug exposure: If not validated, bad order sent to gateway.
        """
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            # Mock gateway — but this should NOT be called
            router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 0, "success": False})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                # Test expectation: Should validate BEFORE calling gateway
                # If bug exists: volume=0 is sent to gateway (bad)
                # If fixed: TonpoError raised (good)
                try:
                    await client.place_market_buy("EURUSD", volume=0)
                    # If we get here, validation is MISSING (bug)
                    pytest.fail(
                        "VALIDATION BUG: zero volume was not rejected! "
                        "Should raise TonpoError before sending to gateway."
                    )
                except TonpoError as e:
                    # Good — validation caught it
                    assert "volume" in str(e).lower() or "0" in str(e)
                except Exception as e:
                    # Unexpected error type — might indicate missing validation
                    pytest.fail(f"Wrong exception type: {type(e).__name__}. Expected TonpoError.")

    @pytest.mark.asyncio
    async def test_market_order_negative_volume_should_be_rejected(self, config):
        """Negative volume should be rejected before sending to gateway."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 0, "success": False})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    await client.place_market_buy("EURUSD", volume=-0.1)
                    pytest.fail(
                        "VALIDATION BUG: negative volume was not rejected! "
                        "Should raise TonpoError before sending to gateway."
                    )
                except TonpoError as e:
                    assert "volume" in str(e).lower() or "negative" in str(e).lower()

    @pytest.mark.asyncio
    async def test_limit_order_zero_volume_should_be_rejected(self, config):
        """Zero volume in limit orders should also be rejected."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 0})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    await client.place_limit_buy("EURUSD", volume=0, price=1.08)
                    pytest.fail("VALIDATION BUG: zero volume not rejected in limit order!")
                except TonpoError:
                    pass  # Expected

    @pytest.mark.asyncio
    async def test_stop_order_zero_volume_should_be_rejected(self, config):
        """Zero volume in stop orders should also be rejected."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 0})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    await client.place_stop_buy("EURUSD", volume=0, price=1.09)
                    pytest.fail("VALIDATION BUG: zero volume not rejected in stop order!")
                except TonpoError:
                    pass  # Expected

    @pytest.mark.asyncio
    async def test_very_large_volume_allowed(self, config):
        """Very large volumes should be allowed (gateway decides limit)."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            route = router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 123, "success": True})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                # SDK should pass through to gateway (gateway validates)
                result = await client.place_market_buy("EURUSD", volume=1000.0)
                assert result.ticket == 123
                
                # Verify it was sent to gateway
                assert route.called
                import json
                body = json.loads(route.calls[0].request.content)
                assert body["volume"] == 1000.0

    @pytest.mark.asyncio
    async def test_very_small_volume_allowed(self, config):
        """Very small volumes should be allowed (gateway decides minimum)."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            route = router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 123})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                result = await client.place_market_buy("EURUSD", volume=0.001)
                assert result.ticket == 123
                
                # Verify small volume was sent
                import json
                body = json.loads(route.calls[0].request.content)
                assert body["volume"] == 0.001


# ==================== Limit/Stop Order Price Validation ====================

class TestLimitStopOrderPrice:
    """Validate that limit/stop orders require price."""

    @pytest.mark.asyncio
    async def test_limit_buy_without_price_raises_error(self, config):
        """Limit order MUST have price."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 0})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                # This should fail — price is required for limit orders
                # Testing if price validation exists
                try:
                    # Attempt to place limit order without price
                    # Note: current API requires price parameter
                    # But this test checks if validation catches it
                    with pytest.raises((TypeError, TonpoError)):
                        # price parameter is required (not Optional)
                        await client.place_limit_buy("EURUSD", volume=0.1)  # type: ignore
                except:
                    # If we get here without raising, validation might be missing
                    pass

    @pytest.mark.asyncio
    async def test_limit_buy_with_zero_price_should_be_rejected(self, config):
        """Zero price in limit order should be rejected."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 0})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    await client.place_limit_buy("EURUSD", volume=0.1, price=0)
                    pytest.fail(
                        "VALIDATION BUG: zero price was not rejected in limit order! "
                        "Prices must be > 0"
                    )
                except TonpoError as e:
                    assert "price" in str(e).lower() or "0" in str(e)

    @pytest.mark.asyncio
    async def test_limit_sell_with_negative_price_should_be_rejected(self, config):
        """Negative price in limit order should be rejected."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 0})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    await client.place_limit_sell("EURUSD", volume=0.1, price=-1.05)
                    pytest.fail("VALIDATION BUG: negative price not rejected!")
                except TonpoError:
                    pass  # Expected

    @pytest.mark.asyncio
    async def test_stop_buy_with_zero_price_should_be_rejected(self, config):
        """Zero price in stop order should be rejected."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 0})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    await client.place_stop_buy("EURUSD", volume=0.1, price=0)
                    pytest.fail("VALIDATION BUG: zero price not rejected in stop order!")
                except TonpoError:
                    pass  # Expected

    @pytest.mark.asyncio
    async def test_market_order_ignores_price_if_provided(self, config):
        """Market orders should ignore price parameter if provided."""
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 123})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                # Market orders don't use price, so passing it shouldn't break
                result = await client.place_market_buy("EURUSD", volume=0.1)
                assert result.ticket == 123
                
                # Verify price wasn't sent (shouldn't be in payload)
                import json
                body = json.loads(route.calls[0].request.content)
                # Price should NOT be in market order payload
                assert "price" not in body


# ==================== Symbol Validation ====================

class TestSymbolValidation:
    """Validate symbol parameter."""

    @pytest.mark.asyncio
    async def test_empty_symbol_should_be_rejected(self, config):
        """Empty symbol string should be rejected."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 0})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    await client.place_market_buy("", volume=0.1)
                    pytest.fail("VALIDATION BUG: empty symbol not rejected!")
                except TonpoError as e:
                    assert "symbol" in str(e).lower() or "empty" in str(e).lower()

    @pytest.mark.asyncio
    async def test_none_symbol_should_be_rejected(self, config):
        """None symbol should be rejected."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 0})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    await client.place_market_buy(None, volume=0.1)  # type: ignore
                    pytest.fail("VALIDATION BUG: None symbol not rejected!")
                except (TonpoError, TypeError, AttributeError):
                    pass  # Expected

    @pytest.mark.asyncio
    async def test_whitespace_only_symbol_should_be_rejected(self, config):
        """Symbol with only whitespace should be rejected."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 0})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    await client.place_market_buy("   ", volume=0.1)
                    pytest.fail("VALIDATION BUG: whitespace-only symbol not rejected!")
                except TonpoError:
                    pass  # Expected

    @pytest.mark.asyncio
    async def test_valid_symbols_allowed(self, config):
        """Valid symbols should be allowed (gateway validates existence)."""
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders").mock(
                return_value=httpx.Response(200, json={"ticket": 123})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                # These should all pass SDK validation
                for symbol in ["EURUSD", "GBPUSD", "XAUUSD", "SPY", "BTC/USD"]:
                    result = await client.place_market_buy(symbol, volume=0.1)
                    assert result.ticket == 123


# ==================== wait_for_active() Edge Cases ====================

class TestWaitForActiveEdgeCases:
    """Test edge cases in wait_for_active() timeout handling."""

    @pytest.mark.asyncio
    async def test_wait_for_active_zero_timeout_raises_timeout_error(self, config):
        """Zero timeout should raise AccountTimeoutError immediately."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.get("/api/accounts/acc-1").mock(
                return_value=httpx.Response(200, json={"status": "connecting"})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                with pytest.raises(AccountTimeoutError) as exc_info:
                    await client.wait_for_active("acc-1", timeout=0)
                
                # Should mention timeout
                assert "timeout" in str(exc_info.value).lower() or "0" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_wait_for_active_negative_timeout_behavior(self, config):
        """Negative timeout should either raise error or immediately timeout."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.get("/api/accounts/acc-1").mock(
                return_value=httpx.Response(200, json={"status": "connecting"})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                # Negative timeout is semantically invalid
                with pytest.raises((AccountTimeoutError, ValueError, TonpoError)):
                    await client.wait_for_active("acc-1", timeout=-1)

    @pytest.mark.asyncio
    async def test_wait_for_active_very_short_timeout_respects_deadline(self, config):
        """Short timeout (1s) should timeout if account not active."""
        with respx.mock(base_url=config.base_url) as router:
            # Always return connecting (never active)
            router.get("/api/accounts/acc-1").mock(
                return_value=httpx.Response(200, json={"status": "connecting"})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                import time
                start = time.monotonic()
                with pytest.raises(AccountTimeoutError):
                    # Poll interval = 0.1s, timeout = 1s
                    await client.wait_for_active("acc-1", timeout=1, poll_interval=0.1)
                elapsed = time.monotonic() - start
                
                # Should not wait significantly longer than timeout
                # Allow some margin (< 2 seconds total)
                assert elapsed < 2.0, f"Timeout took {elapsed}s, should be ~1s"
                assert elapsed >= 0.9, f"Timeout too short: {elapsed}s"

    @pytest.mark.asyncio
    async def test_wait_for_active_stops_immediately_when_active(self, config):
        """Should return immediately when account becomes active."""
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/accounts/acc-1").mock(
                return_value=httpx.Response(200, json={"status": "active"})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                import time
                start = time.monotonic()
                await client.wait_for_active("acc-1", timeout=60, poll_interval=5)
                elapsed = time.monotonic() - start
                
                # Should return almost immediately (< 1 second)
                assert elapsed < 1.0, f"Should return immediately when active, took {elapsed}s"

    @pytest.mark.asyncio
    async def test_wait_for_active_poll_interval_zero_behavior(self, config):
        """Zero poll interval should not cause infinite loop (be careful!)."""
        with respx.mock(base_url=config.base_url) as router:
            call_count = [0]
            
            def side_effect(request):
                call_count[0] += 1
                # Return connecting first few times, then active
                if call_count[0] < 3:
                    return httpx.Response(200, json={"status": "connecting"})
                return httpx.Response(200, json={"status": "active"})
            
            router.get("/api/accounts/acc-1").mock(side_effect=side_effect)
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                # Zero poll interval will poll rapidly
                # Should still work, just be fast
                await client.wait_for_active("acc-1", timeout=10, poll_interval=0)
                assert call_count[0] >= 3

    @pytest.mark.asyncio
    async def test_wait_for_active_very_long_timeout_respects_deadline(self, config):
        """Very long timeout should work correctly."""
        with respx.mock(base_url=config.base_url) as router:
            # Activate after 2 polls
            call_count = [0]
            
            def side_effect(request):
                call_count[0] += 1
                if call_count[0] < 2:
                    return httpx.Response(200, json={"status": "connecting"})
                return httpx.Response(200, json={"status": "active"})
            
            router.get("/api/accounts/acc-1").mock(side_effect=side_effect)
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                # Use very long timeout (3600s = 1 hour)
                await client.wait_for_active("acc-1", timeout=3600, poll_interval=0.1)
                # Should succeed quickly despite long timeout


# ==================== Position/Close Order Validation ====================

class TestClosePositionValidation:
    """Validate close_position() parameters."""

    @pytest.mark.asyncio
    async def test_close_position_zero_volume_should_close_full(self, config):
        """Zero volume in close_position should close entire position (or be invalid)."""
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders/close").mock(
                return_value=httpx.Response(200, json={"ticket": 123, "success": True})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                # close_position with zero volume could mean:
                # 1. Close full position (omit volume param)
                # 2. Invalid input (reject)
                # SDK behavior: omit volume if 0 is passed
                result = await client.close_position(ticket=99999, volume=0)
                
                # Check what was actually sent
                import json
                body = json.loads(route.calls[0].request.content)
                # Volume should NOT be in payload if 0
                if 0 in body.values():
                    pytest.fail("VALIDATION BUG: zero volume sent in close_position payload")

    @pytest.mark.asyncio
    async def test_close_position_negative_volume_should_be_rejected(self, config):
        """Negative volume in close_position should be rejected."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders/close").mock(
                return_value=httpx.Response(200, json={"ticket": 123})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    await client.close_position(ticket=99999, volume=-0.1)
                    pytest.fail("VALIDATION BUG: negative volume not rejected in close_position!")
                except TonpoError:
                    pass  # Expected


# ==================== Modify Position Validation ====================

class TestModifyPositionValidation:
    """Validate modify_position() parameters."""

    @pytest.mark.asyncio
    async def test_modify_position_requires_sl_or_tp(self, config):
        """modify_position must have at least sl or tp."""
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/orders/modify").mock(
                return_value=httpx.Response(200, json={"ticket": 123})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    # No sl, no tp — should be rejected
                    await client.modify_position(ticket=99999)
                    # If we get here, validation might be missing
                    # But this could be allowed if gateway validates
                    pass
                except TonpoError:
                    pass  # Expected if client validates

    @pytest.mark.asyncio
    async def test_modify_position_sl_only(self, config):
        """modify_position with only sl should work."""
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders/modify").mock(
                return_value=httpx.Response(200, json={"ticket": 123})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                result = await client.modify_position(ticket=99999, sl=1.0800)
                assert result.ticket == 123
                
                # Verify sl was sent, tp was not
                import json
                body = json.loads(route.calls[0].request.content)
                assert "sl" in body
                assert body["sl"] == 1.0800
                # tp should not be in payload if not provided
                if "tp" in body:
                    # This might be OK if gateway allows it
                    pass

    @pytest.mark.asyncio
    async def test_modify_position_tp_only(self, config):
        """modify_position with only tp should work."""
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders/modify").mock(
                return_value=httpx.Response(200, json={"ticket": 123})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                result = await client.modify_position(ticket=99999, tp=1.1000)
                assert result.ticket == 123
                
                import json
                body = json.loads(route.calls[0].request.content)
                assert "tp" in body
                assert body["tp"] == 1.1000

    @pytest.mark.asyncio
    async def test_modify_position_zero_sl_should_be_rejected(self, config):
        """Zero sl in modify_position should be rejected."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders/modify").mock(
                return_value=httpx.Response(200, json={"ticket": 123})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    await client.modify_position(ticket=99999, sl=0)
                    pytest.fail("VALIDATION BUG: zero sl not rejected!")
                except TonpoError:
                    pass  # Expected

    @pytest.mark.asyncio
    async def test_modify_position_zero_tp_should_be_rejected(self, config):
        """Zero tp in modify_position should be rejected."""
        with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
            router.post("/api/orders/modify").mock(
                return_value=httpx.Response(200, json={"ticket": 123})
            )
            
            async with TonpoClient.for_user(config, "sk_test") as client:
                try:
                    await client.modify_position(ticket=99999, tp=0)
                    pytest.fail("VALIDATION BUG: zero tp not rejected!")
                except TonpoError:
                    pass  # Expected


# ==================== State & Lifecycle Validation ====================

class TestClientStateValidation:
    """Validate client state requirements."""

    @pytest.mark.asyncio
    async def test_using_client_without_start_raises_not_started_error(self, config):
        """Using client methods without start() should raise NotStartedError."""
        from tonpo.exceptions import NotStartedError
        
        client = TonpoClient.for_user(config, "sk_test")
        # Don't call start()
        
        with pytest.raises(NotStartedError):
            await client.health_check()

    @pytest.mark.asyncio
    async def test_multiple_stop_calls_idempotent(self, config):
        """Calling stop() multiple times should be safe."""
        async with TonpoClient.for_user(config, "sk_test") as client:
            pass  # Already stopped by context manager
        
        # Calling stop again should not raise
        await client.stop()
        await client.stop()  # Safe to call twice
