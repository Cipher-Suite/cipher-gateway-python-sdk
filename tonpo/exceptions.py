# tonpo-py/exceptions.py
"""
Tonpo SDK exception hierarchy.
All exceptions inherit from TonpoError for easy catch-all handling.

    try:
        await client.wait_for_active(account_id)
    except AccountLoginFailedError as e:
        print(f"Wrong credentials: {e}")
    except TonpoError as e:
        print(f"Gateway error: {e}")
"""


class TonpoError(Exception):
    """Base exception for all SDK errors. Catch this for a catch-all."""
    pass


class NotStartedError(TonpoError):
    """Client was used before start() was called (or outside async with block)."""
    pass


class AuthenticationError(TonpoError):
    """API key is missing, invalid, or has been revoked."""
    pass


class AccountNotFoundError(TonpoError):
    """The given account_id does not exist on the gateway."""
    pass


class AccountLoginFailedError(TonpoError):
    """MT5 credentials were rejected by the broker."""
    pass


class AccountTimeoutError(TonpoError):
    """Account did not reach 'active' status within the timeout."""
    pass


class OrderError(TonpoError):
    """Order placement, modification, or close failed."""
    pass


class TonpoConnectionError(TonpoError):
    """
    HTTP or WebSocket connection to the gateway failed.

    Named TonpoError (not ConnectionError) to avoid shadowing
    Python's built-in builtins.ConnectionError, which is a subclass of OSError
    and used by socket/network code throughout the stdlib.
    """
    pass


class SubscriptionError(TonpoError):
    """WebSocket market-data subscription failed or timed out."""
    pass


class TonpoResponseError(TonpoError):
    """
    Tonpo returned an unexpected or malformed HTTP response.

    Attributes:
        status_code: The HTTP status code (e.g. 500).
        raw:         The raw response body (truncated for HTML error pages).
    """
    def __init__(self, message: str, status_code: int = 0, raw: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.raw = raw
