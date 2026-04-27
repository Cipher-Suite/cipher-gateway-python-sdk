# tonpo-py/__init__.py
"""
Tonpo Python SDK
========================
Official Python client for the Tonpo MT5 Gateway (TMG).

Quick start::

    from tonpo import TonpoClient, TonpoConfig

    config = TonpoConfig(
        host="gateway.cipherbridge.cloud",
        port=443,
        use_ssl=True,
    )

    # Create a tonpo user (once per user — store the credentials)
    async with TonpoClient.admin(config) as client:
        user_creds = await client.create_user()

    # Provision an MT5 account (once per account)
    async with TonpoClient.for_user(config, api_key=user_creds.api_key) as client:
        account = await client.create_account("12345", "pass", "ICMarkets-Demo")
        await client.wait_for_active(account.account_id)  # waits up to 180s

    # Trade (use stored api_key + account_id every time)
    async with TonpoClient.for_user(config, api_key=user_creds.api_key) as client:
        info      = await client.get_account_info()
        positions = await client.get_positions()
        result    = await client.place_market_buy("EURUSD", volume=0.1, sl=1.0800)
"""

from .client import TonpoClient
from .models import (
    TonpoConfig,
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
    TonpoError,
    NotStartedError,
    AuthenticationError,
    AccountNotFoundError,
    AccountLoginFailedError,
    AccountTimeoutError,
    OrderError,
    TonpoConnectionError,   # NOT "ConnectionError" — that would shadow builtins.ConnectionError
    SubscriptionError,
    TonpoResponseError,
)

__version__ = "1.0.0"
__author__  = "TonpoLabs"

__all__ = [
    # Main client
    "TonpoClient",

    # Configuration
    "TonpoConfig",

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
    "TonpoError",
    "NotStartedError",
    "AuthenticationError",
    "AccountNotFoundError",
    "AccountLoginFailedError",
    "AccountTimeoutError",
    "OrderError",
    "TonpoConnectionError",
    "SubscriptionError",
    "TonpoResponseError",
]
