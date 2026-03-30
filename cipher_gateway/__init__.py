# cipher_gateway/__init__.py
"""
CipherGateway Python SDK
========================
Official Python client for the Cipher MT5 Gateway.

Quick start:
    from cipher_gateway import CipherGatewayClient, GatewayConfig

    config = GatewayConfig(
        host="gateway.cipherbridge.cloud",
        port=443,
        use_ssl=True,
    )

    # Register a new user
    async with CipherGatewayClient.admin(config) as client:
        user_creds = await client.create_user()

    # All trading operations
    async with CipherGatewayClient.for_user(config, api_key=user_creds.api_key) as client:
        account = await client.create_account("12345", "pass", "ICMarkets-Demo")
        await client.wait_for_active(account.account_id)

        info      = await client.get_account_info()
        positions = await client.get_positions()
        result    = await client.place_market_buy("EURUSD", volume=0.1, sl=1.0800)
"""

from .client import CipherGatewayClient
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
from .exceptions import (
    CipherGatewayError,
    NotStartedError,
    AuthenticationError,
    AccountNotFoundError,
    AccountLoginFailedError,
    AccountTimeoutError,
    OrderError,
    ConnectionError,
    SubscriptionError,
    GatewayResponseError,
)

__version__ = "1.0.0"
__author__  = "CipherTrade"

__all__ = [
    # Main client
    "CipherGatewayClient",

    # Config
    "GatewayConfig",

    # Credential models
    "UserCredentials",
    "AccountCredentials",

    # Data models
    "AccountInfo",
    "Position",
    "OrderResult",
    "SymbolPrice",
    "Quote",
    "Tick",
    "Candle",

    # Exceptions
    "CipherGatewayError",
    "NotStartedError",
    "AuthenticationError",
    "AccountNotFoundError",
    "AccountLoginFailedError",
    "AccountTimeoutError",
    "OrderError",
    "ConnectionError",
    "SubscriptionError",
    "GatewayResponseError",
]
