# tests/test_client.py
"""
Layer 2 — TonpoClient unit tests.
HTTP is mocked with respx. WebSocket is not exercised here.
"""
import pytest
import httpx
import respx

from tonpo.client import TonpoClient
from tonpo.models import TonpoConfig, AccountInfo, Position, OrderResult
from tonpo.exceptions import (
    AccountLoginFailedError,
    AccountTimeoutError,
    TonpoError,
    AuthenticationError,
)


# ==================== Factory methods ====================

class TestFactoryMethods:

    def test_admin_creates_client_without_api_key(self, config):
        client = TonpoClient.admin(config)
        assert client._http._api_key is None

    def test_for_user_sets_api_key(self, config):
        client = TonpoClient.for_user(config, api_key="sk_test")
        assert client._http._api_key == "sk_test"

    def test_for_user_sets_ws_api_key(self, config):
        client = TonpoClient.for_user(config, api_key="sk_test")
        assert client._ws._api_key == "sk_test"


# ==================== Lifecycle ====================

class TestLifecycle:

    @pytest.mark.asyncio
    async def test_context_manager_starts_and_stops(self, config):
        with respx.mock(base_url=config.base_url, assert_all_called=False):
            async with TonpoClient.admin(config) as client:
                assert client._started is True
                assert client._http._client is not None
            assert client._started is False
            assert client._http._client is None


# ==================== Health ====================

class TestHealthCheck:

    @pytest.mark.asyncio
    async def test_health_check_true_on_200(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
            async with TonpoClient.admin(config) as client:
                assert await client.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_false_on_error(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/health").mock(side_effect=httpx.ConnectError("refused"))
            async with TonpoClient.admin(config) as client:
                assert await client.health_check() is False


# ==================== create_user ====================

class TestCreateUser:

    @pytest.mark.asyncio
    async def test_returns_user_credentials(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/users").mock(return_value=httpx.Response(200, json={
                "user_id": "uid-abc",
                "api_key": "sk_live_xyz",
            }))
            async with TonpoClient.admin(config) as client:
                creds = await client.create_user()
            assert creds.gateway_user_id == "uid-abc"
            assert creds.api_key == "sk_live_xyz"

    @pytest.mark.asyncio
    async def test_handles_camel_case_response(self, config):
        """Gateway may return userId/apiKey in camelCase."""
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/users").mock(return_value=httpx.Response(200, json={
                "userId": "uid-abc",
                "apiKey": "sk_live_xyz",
            }))
            async with TonpoClient.admin(config) as client:
                creds = await client.create_user()
            assert creds.gateway_user_id == "uid-abc"
            assert creds.api_key == "sk_live_xyz"

    @pytest.mark.asyncio
    async def test_raises_on_incomplete_response(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/users").mock(return_value=httpx.Response(200, json={}))
            async with TonpoClient.admin(config) as client:
                with pytest.raises(TonpoError):
                    await client.create_user()


# ==================== create_account ====================

class TestCreateAccount:

    @pytest.mark.asyncio
    async def test_sends_camel_case_payload(self, config):
        """
        BUG regression: must send mt5Login/mt5Password/mt5Server not snake_case.
        Gateway CreateAccountRequest uses #[serde(rename_all = "camelCase")].
        """
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/accounts").mock(
                return_value=httpx.Response(201, json={"account_id": "acc-123", "auth_token": "tok"})
            )
            async with TonpoClient.for_user(config, "sk_test") as client:
                account = await client.create_account("12345678", "pass", "ICMarkets-Demo")

            # Inspect what was actually sent
            sent = route.calls[0].request
            import json
            body = json.loads(sent.content)
            assert "mt5Login"    in body, "Must send mt5Login (camelCase)"
            assert "mt5Password" in body, "Must send mt5Password (camelCase)"
            assert "mt5Server"   in body, "Must send mt5Server (camelCase)"
            assert "mt5_login"    not in body, "Must NOT send mt5_login (snake_case)"
            assert "mt5_password" not in body
            assert "mt5_server"   not in body

    @pytest.mark.asyncio
    async def test_returns_account_credentials(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/accounts").mock(return_value=httpx.Response(201, json={
                "account_id": "acc-abc-123",
                "auth_token": "tok_xyz",
            }))
            async with TonpoClient.for_user(config, "sk_test") as client:
                creds = await client.create_account("12345", "pass", "Demo-Server")
            assert creds.account_id == "acc-abc-123"
            assert creds.auth_token == "tok_xyz"

    @pytest.mark.asyncio
    async def test_sends_optional_region(self, config):
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/accounts").mock(
                return_value=httpx.Response(201, json={"account_id": "acc-1"})
            )
            async with TonpoClient.for_user(config, "sk_test") as client:
                await client.create_account("123", "pass", "Demo", region="eu")
            import json
            body = json.loads(route.calls[0].request.content)
            assert body.get("region") == "eu"

    @pytest.mark.asyncio
    async def test_raises_on_missing_account_id(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/accounts").mock(
                return_value=httpx.Response(201, json={"status": "created"})
            )
            async with TonpoClient.for_user(config, "sk_test") as client:
                with pytest.raises(TonpoError):
                    await client.create_account("123", "pass", "Demo")


# ==================== wait_for_active ====================

class TestWaitForActive:

    @pytest.mark.asyncio
    async def test_returns_immediately_when_active(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/accounts/acc-1").mock(return_value=httpx.Response(200, json={
                "status": "active", "last_error": None
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                # Should not raise
                await client.wait_for_active("acc-1", timeout=10, poll_interval=1)

    @pytest.mark.asyncio
    async def test_raises_login_failed(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/accounts/acc-1").mock(return_value=httpx.Response(200, json={
                "status": "login_failed",
                "last_error": "Invalid credentials"
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                with pytest.raises(AccountLoginFailedError) as exc_info:
                    await client.wait_for_active("acc-1", timeout=10, poll_interval=1)
            assert "Invalid credentials" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_login_failed_with_none_last_error(self, config):
        """
        BUG regression: when last_error key exists but value is None,
        dict.get(key, default) returns None — must use 'or' fallback.
        """
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/accounts/acc-1").mock(return_value=httpx.Response(200, json={
                "status": "login_failed",
                "last_error": None          # key exists, value is None
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                with pytest.raises(AccountLoginFailedError) as exc_info:
                    await client.wait_for_active("acc-1", timeout=10, poll_interval=1)
            # Must NOT be "None" — must be the fallback message
            assert str(exc_info.value) != "None"
            assert len(str(exc_info.value)) > 5

    @pytest.mark.asyncio
    async def test_raises_timeout(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/accounts/acc-1").mock(return_value=httpx.Response(200, json={
                "status": "connecting", "last_error": None
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                with pytest.raises(AccountTimeoutError):
                    await client.wait_for_active("acc-1", timeout=1, poll_interval=1)

    @pytest.mark.asyncio
    async def test_polls_until_active(self, config):
        """Simulate: first two polls return 'connecting', third returns 'active'."""
        responses = iter([
            httpx.Response(200, json={"status": "connecting", "last_error": None}),
            httpx.Response(200, json={"status": "connecting", "last_error": None}),
            httpx.Response(200, json={"status": "active",     "last_error": None}),
        ])
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/accounts/acc-1").mock(side_effect=lambda _: next(responses))
            async with TonpoClient.for_user(config, "sk") as client:
                await client.wait_for_active("acc-1", timeout=30, poll_interval=0)


# ==================== Account management ====================

class TestAccountManagement:

    @pytest.mark.asyncio
    async def test_get_account_status(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/accounts/acc-1").mock(return_value=httpx.Response(200, json={
                "account_id": "acc-1", "status": "active"
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                status = await client.get_account_status("acc-1")
            assert status["status"] == "active"

    @pytest.mark.asyncio
    async def test_delete_account(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.delete("/api/accounts/acc-1").mock(
                return_value=httpx.Response(200, json={"message": "deleted"})
            )
            async with TonpoClient.for_user(config, "sk") as client:
                result = await client.delete_account("acc-1")
            assert result is True

    @pytest.mark.asyncio
    async def test_pause_account(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/accounts/acc-1/pause").mock(
                return_value=httpx.Response(200, json={})
            )
            async with TonpoClient.for_user(config, "sk") as client:
                result = await client.pause_account("acc-1")
            assert result is True

    @pytest.mark.asyncio
    async def test_resume_account(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/accounts/acc-1/resume").mock(
                return_value=httpx.Response(200, json={})
            )
            async with TonpoClient.for_user(config, "sk") as client:
                result = await client.resume_account("acc-1")
            assert result is True

    @pytest.mark.asyncio
    async def test_get_accounts(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/accounts").mock(return_value=httpx.Response(200, json={
                "accounts": [{"account_id": "acc-1"}, {"account_id": "acc-2"}]
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                accounts = await client.get_accounts()
            assert len(accounts) == 2


# ==================== Account info + positions ====================

class TestAccountInfoAndPositions:

    @pytest.mark.asyncio
    async def test_get_account_info(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/account").mock(return_value=httpx.Response(200, json={
                "account": {
                    "login": 12345678, "name": "Test", "server": "ICMarkets-Demo",
                    "balance": 10000.0, "equity": 10000.0, "margin": 0.0,
                    "free_margin": 10000.0, "leverage": 100, "currency": "USD",
                    "profit": 0.0,
                }
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                info = await client.get_account_info()
            assert isinstance(info, AccountInfo)
            assert info.login == 12345678
            assert info.balance == 10000.0

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/positions").mock(return_value=httpx.Response(200, json={
                "positions": []
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                positions = await client.get_positions()
            assert positions == []

    @pytest.mark.asyncio
    async def test_get_positions_parses_list(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/positions").mock(return_value=httpx.Response(200, json={
                "positions": [
                    {"ticket": 1, "symbol": "EURUSD", "side": "buy", "volume": 0.1,
                     "openPrice": 1.08, "currentPrice": 1.09, "profit": 100.0,
                     "swap": 0, "commission": 0},
                ]
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                positions = await client.get_positions()
            assert len(positions) == 1
            assert isinstance(positions[0], Position)
            assert positions[0].symbol == "EURUSD"


# ==================== Orders ====================

class TestOrders:

    def _order_response(self, ticket=999, success=True):
        return httpx.Response(200, json={"ticket": ticket, "success": success, "error": None})

    @pytest.mark.asyncio
    async def test_place_market_buy_payload(self, config):
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders").mock(return_value=self._order_response())
            async with TonpoClient.for_user(config, "sk") as client:
                await client.place_market_buy("EURUSD", volume=0.1, sl=1.0800, tp=1.1000)
            import json
            body = json.loads(route.calls[0].request.content)
            assert body["symbol"]    == "EURUSD"
            assert body["side"]      == "buy"
            assert body["orderType"] == "market"
            assert body["volume"]    == 0.1
            assert body["sl"]        == 1.0800
            assert body["tp"]        == 1.1000

    @pytest.mark.asyncio
    async def test_place_market_sell_payload(self, config):
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders").mock(return_value=self._order_response())
            async with TonpoClient.for_user(config, "sk") as client:
                await client.place_market_sell("GBPUSD", volume=0.2)
            import json
            body = json.loads(route.calls[0].request.content)
            assert body["side"]  == "sell"
            assert body["orderType"] == "market"

    @pytest.mark.asyncio
    async def test_place_limit_buy_includes_price(self, config):
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders").mock(return_value=self._order_response())
            async with TonpoClient.for_user(config, "sk") as client:
                await client.place_limit_buy("EURUSD", volume=0.1, price=1.0750)
            import json
            body = json.loads(route.calls[0].request.content)
            assert body["orderType"] == "limit"
            assert body["price"]     == 1.0750

    @pytest.mark.asyncio
    async def test_place_stop_sell_includes_price(self, config):
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders").mock(return_value=self._order_response())
            async with TonpoClient.for_user(config, "sk") as client:
                await client.place_stop_sell("EURUSD", volume=0.1, price=1.0700)
            import json
            body = json.loads(route.calls[0].request.content)
            assert body["orderType"] == "stop"
            assert body["side"]      == "sell"

    @pytest.mark.asyncio
    async def test_optional_fields_omitted_when_not_provided(self, config):
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders").mock(return_value=self._order_response())
            async with TonpoClient.for_user(config, "sk") as client:
                await client.place_market_buy("EURUSD", volume=0.1)
            import json
            body = json.loads(route.calls[0].request.content)
            assert "sl"      not in body
            assert "tp"      not in body
            assert "comment" not in body
            assert "magic"   not in body

    @pytest.mark.asyncio
    async def test_magic_and_comment_sent_when_provided(self, config):
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders").mock(return_value=self._order_response())
            async with TonpoClient.for_user(config, "sk") as client:
                await client.place_market_buy(
                    "EURUSD", volume=0.1, comment="bot", magic=42
                )
            import json
            body = json.loads(route.calls[0].request.content)
            assert body["comment"] == "bot"
            assert body["magic"]   == 42

    @pytest.mark.asyncio
    async def test_order_result_parsed(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/orders").mock(return_value=httpx.Response(200, json={
                "ticket": 12345, "success": True, "error": None
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                result = await client.place_market_buy("EURUSD", volume=0.1)
            assert isinstance(result, OrderResult)
            assert result.ticket  == 12345
            assert result.success is True

    @pytest.mark.asyncio
    async def test_close_position_full(self, config):
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders/close").mock(return_value=self._order_response())
            async with TonpoClient.for_user(config, "sk") as client:
                result = await client.close_position(ticket=99999)
            import json
            body = json.loads(route.calls[0].request.content)
            assert body["ticket"] == 99999
            assert "volume" not in body

    @pytest.mark.asyncio
    async def test_close_position_partial(self, config):
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders/close").mock(return_value=self._order_response())
            async with TonpoClient.for_user(config, "sk") as client:
                await client.close_position(ticket=99999, volume=0.05)
            import json
            body = json.loads(route.calls[0].request.content)
            assert body["volume"] == 0.05

    @pytest.mark.asyncio
    async def test_modify_position(self, config):
        with respx.mock(base_url=config.base_url) as router:
            route = router.post("/api/orders/modify").mock(return_value=self._order_response())
            async with TonpoClient.for_user(config, "sk") as client:
                await client.modify_position(ticket=99999, sl=1.0800, tp=1.1000)
            import json
            body = json.loads(route.calls[0].request.content)
            assert body["ticket"] == 99999
            assert body["sl"]     == 1.0800
            assert body["tp"]     == 1.1000


# ==================== Symbol price ====================

class TestSymbolPrice:

    @pytest.mark.asyncio
    async def test_get_symbol_price_from_rest(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/symbols/EURUSD").mock(return_value=httpx.Response(200, json={
                "bid": 1.0850, "ask": 1.0852
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                price = await client.get_symbol_price("EURUSD")
            assert price.bid == 1.0850
            assert price.ask == 1.0852

    @pytest.mark.asyncio
    async def test_get_symbol_price_falls_back_to_cache(self, config):
        with respx.mock(base_url=config.base_url) as router:
            # REST returns zeros → should fall back to cache
            router.get("/api/symbols/EURUSD").mock(return_value=httpx.Response(200, json={
                "bid": 0, "ask": 0
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                # Manually populate the WS price cache
                client._ws._price_cache["EURUSD"] = {
                    "bid": 1.0850, "ask": 1.0852, "last": 0, "time": 0
                }
                price = await client.get_symbol_price("EURUSD")
            assert price.bid == 1.0850

    @pytest.mark.asyncio
    async def test_get_symbol_price_raises_when_no_data(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/symbols/UNKNOWN").mock(return_value=httpx.Response(200, json={
                "bid": 0, "ask": 0
            }))
            async with TonpoClient.for_user(config, "sk") as client:
                with pytest.raises(TonpoError):
                    await client.get_symbol_price("UNKNOWN")
