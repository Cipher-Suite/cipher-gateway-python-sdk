# cipher_gateway/exceptions.py
"""
CipherGateway SDK exceptions.
Standalone — no dependencies on the bot application.
"""


class CipherGatewayError(Exception):
    """Base exception for all SDK errors"""
    pass


class NotStartedError(CipherGatewayError):
    """Client used before start() was called"""
    pass


class AuthenticationError(CipherGatewayError):
    """Invalid or missing API key"""
    pass


class AccountNotFoundError(CipherGatewayError):
    """Account ID does not exist on gateway"""
    pass


class AccountLoginFailedError(CipherGatewayError):
    """MT5 credentials were rejected by the broker"""
    pass


class AccountTimeoutError(CipherGatewayError):
    """Account did not become active within the timeout"""
    pass


class OrderError(CipherGatewayError):
    """Order placement, modification or close failed"""
    pass


class ConnectionError(CipherGatewayError):
    """HTTP or WebSocket connection to gateway failed"""
    pass


class SubscriptionError(CipherGatewayError):
    """WebSocket market data subscription failed"""
    pass


class GatewayResponseError(CipherGatewayError):
    """Gateway returned an unexpected or malformed response"""
    def __init__(self, message: str, status_code: int = 0, raw: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.raw = raw
