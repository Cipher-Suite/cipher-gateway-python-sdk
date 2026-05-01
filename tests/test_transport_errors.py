# tests/test_transport_errors.py
"""
Extended transport layer error tests.
Covers all HTTP error codes, HTML stripping, error message truncation, and connection failures.
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


# ==================== HTTP 4xx Client Errors ====================

class TestClientErrors:
    """Test HTTP 4xx error responses — client-side errors."""

    @pytest.mark.asyncio
    async def test_400_bad_request_raises_response_error(self, config):
        """HTTP 400 — malformed request (client fault)."""
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(400, text="Invalid request body")
            )
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.post("/api/orders", json={"invalid": "payload"})
            await t.stop()
            assert exc_info.value.status_code == 400
            assert "Invalid request body" in exc_info.value.raw

    @pytest.mark.asyncio
    async def test_400_with_json_error_message(self, config):
        """HTTP 400 with structured JSON error."""
        json_error = '{"error": "missing field: volume", "code": "VALIDATION_ERROR"}'
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/orders").mock(return_value=httpx.Response(400, text=json_error))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.post("/api/orders", json={})
            await t.stop()
            assert "VALIDATION_ERROR" in exc_info.value.raw
            assert "volume" in exc_info.value.raw

    @pytest.mark.asyncio
    async def test_429_too_many_requests(self, config):
        """HTTP 429 — rate limit exceeded."""
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(429, text="Rate limit exceeded. Retry after 60s")
            )
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.post("/api/orders", json={"symbol": "EURUSD"})
            await t.stop()
            assert exc_info.value.status_code == 429
            # Rate limit info should be in the error
            assert "Rate limit" in exc_info.value.raw

    @pytest.mark.asyncio
    async def test_429_retry_after_header(self, config):
        """HTTP 429 with Retry-After header (future: implement retry logic)."""
        with respx.mock(base_url=config.base_url) as router:
            response = httpx.Response(429, text="Too many requests")
            response.headers["Retry-After"] = "60"
            router.get("/api/account").mock(return_value=response)
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/api/account")
            await t.stop()
            assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_422_unprocessable_entity(self, config):
        """HTTP 422 — validation error (semantically invalid)."""
        error_text = '{"errors": ["mt5_login must be numeric", "mt5_server invalid"]}'
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/accounts").mock(return_value=httpx.Response(422, text=error_text))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.post("/api/accounts", json={"mt5_login": "abc"})
            await t.stop()
            assert exc_info.value.status_code == 422
            assert "numeric" in exc_info.value.raw

    @pytest.mark.asyncio
    async def test_405_method_not_allowed(self, config):
        """HTTP 405 — wrong HTTP method for endpoint."""
        with respx.mock(base_url=config.base_url) as router:
            # GET on a POST-only endpoint
            router.get("/api/accounts").mock(
                return_value=httpx.Response(405, text="Method GET not allowed")
            )
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/api/accounts")
            await t.stop()
            assert exc_info.value.status_code == 405

    @pytest.mark.asyncio
    async def test_410_gone(self, config):
        """HTTP 410 — resource permanently deleted."""
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/accounts/deleted-account").mock(
                return_value=httpx.Response(410, text="Account has been permanently deleted")
            )
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/api/accounts/deleted-account")
            await t.stop()
            assert exc_info.value.status_code == 410


# ==================== HTTP 5xx Server Errors ====================

class TestServerErrors:
    """Test HTTP 5xx error responses — server-side errors."""

    @pytest.mark.asyncio
    async def test_500_internal_server_error(self, config):
        """HTTP 500 — generic server error."""
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
            assert "Internal Server Error" in exc_info.value.raw

    @pytest.mark.asyncio
    async def test_501_not_implemented(self, config):
        """HTTP 501 — endpoint not yet implemented."""
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/experimental/feature").mock(
                return_value=httpx.Response(501, text="Feature not implemented")
            )
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/api/experimental/feature")
            await t.stop()
            assert exc_info.value.status_code == 501

    @pytest.mark.asyncio
    async def test_502_bad_gateway(self, config):
        """HTTP 502 — gateway/proxy error."""
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/health").mock(
                return_value=httpx.Response(502, text="Bad Gateway")
            )
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/api/health")
            await t.stop()
            assert exc_info.value.status_code == 502

    @pytest.mark.asyncio
    async def test_503_service_unavailable(self, config):
        """HTTP 503 — server temporarily unavailable (maintenance/overload)."""
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(503, text="Service Unavailable")
            )
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.post("/api/orders", json={"symbol": "EURUSD"})
            await t.stop()
            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_503_with_retry_after(self, config):
        """HTTP 503 with Retry-After header."""
        with respx.mock(base_url=config.base_url) as router:
            response = httpx.Response(503, text="Maintenance in progress")
            response.headers["Retry-After"] = "120"
            router.get("/api/account").mock(return_value=response)
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/api/account")
            await t.stop()
            assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_504_gateway_timeout(self, config):
        """HTTP 504 — gateway timeout (backend didn't respond in time)."""
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/orders").mock(
                return_value=httpx.Response(504, text="Gateway Timeout")
            )
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.post("/api/orders", json={"symbol": "EURUSD"})
            await t.stop()
            assert exc_info.value.status_code == 504


# ==================== HTML Error Pages (Nginx/Proxy) ====================

class TestHtmlErrorPages:
    """Test HTML error page stripping (proxy/nginx errors)."""

    @pytest.mark.asyncio
    async def test_502_bad_gateway_html_page(self, config):
        """Nginx returns HTML 502 — must strip HTML."""
        html_page = """
        <html>
        <head><title>502 Bad Gateway</title></head>
        <body>
        <center><h1>502 Bad Gateway</h1></center>
        <hr><center>nginx/1.14.0</center>
        </body>
        </html>
        """
        with respx.mock(base_url=config.base_url) as router:
            router.get("/health").mock(return_value=httpx.Response(502, text=html_page))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/health")
            await t.stop()
            # HTML tags must NOT appear in the error message
            assert "<html>" not in str(exc_info.value)
            assert "<body>" not in str(exc_info.value)
            assert "nginx" not in str(exc_info.value)
            # But status code should be visible
            assert "502" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_503_service_unavailable_html(self, config):
        """Nginx 503 HTML error page."""
        html_page = """
        <html>
        <head><title>503 Service Temporarily Unavailable</title></head>
        <body><h1>Service Temporarily Unavailable</h1></body>
        </html>
        """
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/orders").mock(return_value=httpx.Response(503, text=html_page))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.post("/api/orders")
            await t.stop()
            error_str = str(exc_info.value)
            assert "<html>" not in error_str
            assert "503" in error_str

    @pytest.mark.asyncio
    async def test_504_gateway_timeout_html(self, config):
        """Nginx 504 Gateway Timeout HTML."""
        html_page = "<html><body><h1>504 Gateway Time-out</h1></body></html>"
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/account").mock(return_value=httpx.Response(504, text=html_page))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/api/account")
            await t.stop()
            assert "<html>" not in str(exc_info.value)
            assert "504" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_error_page_with_uppercase_html(self, config):
        """HTML detection is case-insensitive."""
        html_page = "<HTML><BODY>ERROR</BODY></HTML>"
        with respx.mock(base_url=config.base_url) as router:
            router.get("/health").mock(return_value=httpx.Response(502, text=html_page))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/health")
            await t.stop()
            # Even uppercase <HTML> should be detected and stripped
            assert "502" in str(exc_info.value)


# ==================== Error Message Truncation ====================

class TestErrorMessageTruncation:
    """Test that long error messages are truncated safely."""

    @pytest.mark.asyncio
    async def test_error_message_truncated_at_300_chars(self, config):
        """Very long error messages should be truncated to 300 chars."""
        long_error = "This is a very long error message. " * 30  # ~1050 chars
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/account").mock(return_value=httpx.Response(500, text=long_error))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/api/account")
            await t.stop()
            # The error message shown to user should be truncated
            error_detail = exc_info.value.args[0]
            assert len(error_detail) <= 310  # 300 + some margin
            # But the full raw should still be stored
            assert len(exc_info.value.raw) > 300

    @pytest.mark.asyncio
    async def test_error_shorter_than_300_chars_not_truncated(self, config):
        """Short errors should be shown in full."""
        short_error = "Request validation failed"
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/accounts").mock(return_value=httpx.Response(400, text=short_error))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.post("/api/accounts")
            await t.stop()
            # Short errors shown in full
            assert short_error in str(exc_info.value)
            assert exc_info.value.raw == short_error

    @pytest.mark.asyncio
    async def test_html_page_stripped_before_truncation(self, config):
        """HTML should be stripped even if message would be truncated."""
        # HTML page is long, should be stripped AND truncated
        html_page = "<html><body>" + ("X" * 500) + "</body></html>"
        with respx.mock(base_url=config.base_url) as router:
            router.get("/health").mock(return_value=httpx.Response(502, text=html_page))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/health")
            await t.stop()
            error_str = str(exc_info.value)
            # HTML must be stripped
            assert "<html>" not in error_str.lower()
            # And message should indicate it's a proxy error
            assert "proxy error" in error_str.lower() or "502" in error_str


# ==================== Connection Errors ====================

class TestConnectionErrors:
    """Test network-level failures."""

    @pytest.mark.asyncio
    async def test_connection_refused(self, config):
        """Server is down — connection refused."""
        with respx.mock(base_url=config.base_url) as router:
            router.get("/health").mock(side_effect=httpx.ConnectError("Connection refused"))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoConnectionError) as exc_info:
                await t.get("/health")
            await t.stop()
            assert "Connection refused" in str(exc_info.value)
            assert "GET /health" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_connection_timeout(self, config):
        """Connection takes too long."""
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/account").mock(side_effect=httpx.ConnectError("Timeout"))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoConnectionError) as exc_info:
                await t.get("/api/account")
            await t.stop()
            assert "Timeout" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_read_timeout(self, config):
        """Response takes too long (server hung)."""
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/orders").mock(side_effect=httpx.ReadTimeout("Server not responding"))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoConnectionError) as exc_info:
                await t.post("/api/orders", json={})
            await t.stop()
            assert "Server not responding" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_dns_resolution_failure(self, config):
        """DNS lookup failed."""
        with respx.mock(base_url=config.base_url) as router:
            # Simulate DNS error by hostname that can't resolve
            router.get("/health").mock(side_effect=httpx.ConnectError("Cannot resolve hostname"))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoConnectionError):
                await t.get("/health")
            await t.stop()

    @pytest.mark.asyncio
    async def test_ssl_certificate_error(self, config):
        """SSL certificate validation failed."""
        with respx.mock(base_url=config.base_url) as router:
            router.get("/health").mock(side_effect=httpx.SSLError("certificate verify failed"))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoConnectionError) as exc_info:
                await t.get("/health")
            await t.stop()
            assert "certificate" in str(exc_info.value).lower()


# ==================== HTTP Verb Error Paths ====================

class TestHttpVerbErrorHandling:
    """Test error handling across all HTTP verbs."""

    @pytest.mark.asyncio
    async def test_post_connection_error(self, config):
        """POST request connection error."""
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/accounts").mock(side_effect=httpx.ConnectError("refused"))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoConnectionError) as exc_info:
                await t.post("/api/accounts", json={})
            await t.stop()
            assert "POST /api/accounts" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_delete_connection_error(self, config):
        """DELETE request connection error."""
        with respx.mock(base_url=config.base_url) as router:
            router.delete("/api/accounts/123").mock(side_effect=httpx.ConnectError("refused"))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoConnectionError) as exc_info:
                await t.delete("/api/accounts/123")
            await t.stop()
            assert "DELETE /api/accounts/123" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_patch_connection_error(self, config):
        """PATCH request connection error."""
        with respx.mock(base_url=config.base_url) as router:
            router.patch("/api/accounts/123").mock(side_effect=httpx.ConnectError("refused"))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoConnectionError) as exc_info:
                await t.patch("/api/accounts/123", json={})
            await t.stop()
            assert "PATCH /api/accounts/123" in str(exc_info.value)


# ==================== Edge Cases ====================

class TestEdgeCases:
    """Test unusual but valid scenarios."""

    @pytest.mark.asyncio
    async def test_200_with_empty_response_body(self, config):
        """HTTP 200 with no JSON — should return empty dict."""
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/health").mock(return_value=httpx.Response(200, text=""))
            t = HttpTransport(config)
            await t.start()
            result = await t.get("/api/health")
            await t.stop()
            assert result == {}

    @pytest.mark.asyncio
    async def test_200_with_invalid_json(self, config):
        """HTTP 200 with malformed JSON — should return empty dict."""
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/health").mock(return_value=httpx.Response(200, text="{invalid}"))
            t = HttpTransport(config)
            await t.start()
            result = await t.get("/api/health")
            await t.stop()
            assert result == {}

    @pytest.mark.asyncio
    async def test_201_with_invalid_json(self, config):
        """HTTP 201 with malformed JSON — should return empty dict."""
        with respx.mock(base_url=config.base_url) as router:
            router.post("/api/accounts").mock(return_value=httpx.Response(201, text="<!DOCTYPE>"))
            t = HttpTransport(config)
            await t.start()
            result = await t.post("/api/accounts")
            await t.stop()
            assert result == {}

    @pytest.mark.asyncio
    async def test_error_with_null_status_code(self, config):
        """Unusual: error response with no status (shouldn't happen, but defensive)."""
        with respx.mock(base_url=config.base_url) as router:
            # httpx Response always has status_code, but test raw exception handling
            router.get("/api/account").mock(side_effect=RuntimeError("Unknown error"))
            t = HttpTransport(config)
            await t.start()
            # RequestError subclasses should be caught
            with pytest.raises(TonpoConnectionError):
                await t.get("/api/account")
            await t.stop()


# ==================== Error Context & Debugging ====================

class TestErrorContext:
    """Test that errors contain useful debugging info."""

    @pytest.mark.asyncio
    async def test_response_error_contains_status_code(self, config):
        """TonpoResponseError must include status_code."""
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/account").mock(return_value=httpx.Response(418, text="I'm a teapot"))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/api/account")
            await t.stop()
            assert exc_info.value.status_code == 418

    @pytest.mark.asyncio
    async def test_response_error_contains_raw_body(self, config):
        """TonpoResponseError must include raw response body."""
        body = '{"error": "Invalid symbol", "details": "XYZUSD not found"}'
        with respx.mock(base_url=config.base_url) as router:
            router.get("/api/symbols/XYZUSD").mock(return_value=httpx.Response(400, text=body))
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoResponseError) as exc_info:
                await t.get("/api/symbols/XYZUSD")
            await t.stop()
            assert "Invalid symbol" in exc_info.value.raw
            assert exc_info.value.raw == body

    @pytest.mark.asyncio
    async def test_connection_error_preserves_original_exception(self, config):
        """TonpoConnectionError should chain the original httpx exception."""
        with respx.mock(base_url=config.base_url) as router:
            original_error = httpx.ConnectError("Connection refused by host")
            router.get("/health").mock(side_effect=original_error)
            t = HttpTransport(config)
            await t.start()
            with pytest.raises(TonpoConnectionError) as exc_info:
                await t.get("/health")
            await t.stop()
            # The cause should be the original httpx error
            assert exc_info.value.__cause__ is original_error
