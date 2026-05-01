# tests/conftest.py
"""
Shared pytest fixtures for all SDK test layers.
"""
import pytest
import httpx
import respx

from tonpo.models import TonpoConfig


# Configs 
@pytest.fixture
def config():
    """Plain HTTP config used for mocked unit tests."""
    return TonpoConfig(
        host="testgateway.local",
        port=8080,
        use_ssl=False,
        request_timeout=5.0,
        connect_timeout=2.0,
        ws_reconnect_delay=0.01,   # fast reconnect in tests
        max_reconnect_attempts=2,
    )


@pytest.fixture
def ssl_config():
    """HTTPS config for URL-scheme tests."""
    return TonpoConfig(
        host="gateway.example.com",
        port=443,
        use_ssl=True,
    )


# Gateway mock 
@pytest.fixture
def mock_gateway(config):
    """
    respx router that intercepts all httpx calls to the test gateway.
    Tests add routes before making calls.
    """
    with respx.mock(base_url=config.base_url, assert_all_called=False) as router:
        yield router
