# tests/test_transport.py
"""
Layer 1 — HttpTransport unit tests.
All HTTP calls are intercepted by respx — no real network.
"""
import pytest
import httpx
import respx

from tonpo.transport import HttpTransport
from tonpo.models import TonpoConfig
from tonpo.exceptions import (
    AuthenticationError,
    AccountNotFoundError,
    TonpoConnectionError,
    TonpoResponseError,
    NotStartedError,
)


@pytest.fixture
def transport(config):
    return HttpTransport(config)


@pytest.fixture
async def started_transport(config):
    t = HttpTransport(config)
    await t.start()
    yield t
    await t.stop()


# ==================== Lifecycle ====================

class TestTransportLifecycle:

    @pytest.mark.asyncio
    async def test_not_started_raises(self, transport):
        with pytest.raises(NotStartedError):
            await transport.get("/health")

    @pytest.mark.asyncio
    async def test_start_stop(self, transport):
        await transport.start()
        assert transport._client is not None
        await transport.stop()
        assert transport._client is None

    @pytest.mark.asyncio
    async def test_stop_when_not_started_is_safe(self, transport):
        await transport.stop()   # must not raise


# ==================== Auth header ====================

class TestAuthHeader:

    @pytest.mark.asyncio
    async def test_no_api_key_no_header(self, config):
        t = HttpTransport(config)
        headers = t._headers()
        assert config.api_key_header not in headers

    @pytest.mark.asyncio
    async def test_api_key_injected(self, config):
        t = HttpTransport(config)
        t.set_api_key("sk_test_123")
        headers = t._headers()
        assert headers[config.api_key_header] == "sk_test_123"

    @pytest.mark.asyncio
    async def test_api_key_sent_in_request(self, config):
        with respx.mock(base_url=config.base_url) as router:
            route = router.get("/health").mock(return_value=httpx.Response(200, json={"ok": True}))
            t = HttpTransport(config)
            t.set_api_key("sk_live_abc")
            await t.start()
            await t.get("/health")
            await t.stop()
            assert route.called
            assert route.calls[0].request.headers.get("X-API-Key") == "sk_live_abc"


# ==================== Status code → exception mapping ====================

class TestStatusCodeMapping:

    @pytest.mark.asyncio
    async def test_200_returns_json(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/test").mock(return_value=httpx.Response(200, json={"key": "value"}))
            t = HttpTransport(config)
            await t.start()
            result = await t.get("/api/test")
            await t.stop()
            assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_201_returns_json(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/accounts").mock(
                return_value=httpx.Response(201, json={"account_id": "abc-123"})
            )
            t = HttpTransport(config)
            await t.start()
            result = await t.post("/api/accounts", json={"mt5Login": "123"})
            await t.stop()
            assert result["account_id"] == "abc-123"

    @pytest.mark.asyncio
    async def test_204_returns_empty_dict(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.delete("/api/accounts/abc").mock(return_value=httpx.Response(204))
            t = HttpTransport(config)
            await t.start()
            result = await t.delete("/api/accounts/abc")
            await t.stop()
            assert result == {}

    @pytest.mark.asyncio
    async def test_401_raises_authentication_error(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/account").mock(return_value=httpx.Response(401))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(AuthenticationError):
                await t.get("/api/account")
            await t.stop()

    @pytest.mark.asyncio
    async def test_403_raises_authentication_error(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/account").mock(return_value=httpx.Response(403))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(AuthenticationError):
                await t.get("/api/account")
            await t.stop()

    @pytest.mark.asyncio
    async def test_404_raises_account_not_found(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/accounts/bad-id").mock(return_value=httpx.Response(404))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(AccountNotFoundError):
                await t.get("/api/accounts/bad-id")
            await t.stop()

    @pytest.mark.asyncio
    async def test_500_raises_gateway_response_error(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/account").mock(
                return_value=httpx.Response(500, text="Internal Server Error")
            )
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/api/account")
            await t.stop()
            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_422_raises_gateway_response_error_with_body(self, config):
        body = '{"error": "missing field mt5Login"}'
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/accounts").mock(
                return_value=httpx.Response(422, text=body)
            )
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.post("/api/accounts", json={})
            await t.stop()
            assert exc_info.value.status_code == 422
            assert "mt5Login" in exc_info.value.raw

    @pytest.mark.asyncio
    async def test_html_error_page_stripped(self, config):
        html = "<html><body><h1>502 Bad Gateway</h1></body></html>"
        with respx.mock(base_url=config.base_url) as router:
            router.get("/health").mock(return_value=httpx.Response(502, text=html))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/health")
            await t.stop()
            # HTML must be stripped from the user-facing message
            assert "<html>" not in str(exc_info.value)
            assert "502" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_network_error_raises_gateway_connection_error(self, config):
        with respx.mock(base_url=config.base_url) as router:
            router.get("/health").mock(side_effect=httpx.ConnectError("refused"))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoConnectionError):
                await t.get("/health")
            await t.stop()
