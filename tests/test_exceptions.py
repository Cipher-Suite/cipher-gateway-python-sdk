# tests/test_exceptions.py
"""
Layer 1 — Exception hierarchy tests.
"""
import builtins
import pytest
from tonpo.exceptions import (
    TonpoError,
    NotStartedError,
    AuthenticationError,
    AccountNotFoundError,
    AccountLoginFailedError,
    AccountTimeoutError,
    OrderError,
    TonpoConnectionError,
    SubscriptionError,
    TonpoResponseError,
)


class TestExceptionHierarchy:

    def test_all_inherit_from_base(self):
        for exc_class in [
            NotStartedError,
            AuthenticationError,
            AccountNotFoundError,
            AccountLoginFailedError,
            AccountTimeoutError,
            OrderError,
            TonpoConnectionError,
            SubscriptionError,
            TonpoResponseError,
        ]:
            assert issubclass(exc_class, TonpoError), \
                f"{exc_class.__name__} must inherit from TonpoError"

    def test_base_inherits_from_exception(self):
        assert issubclass(TonpoError, Exception)

    def test_catch_all_works(self):
        for exc_class in [AuthenticationError, AccountLoginFailedError,
                          TonpoConnectionError, OrderError]:
            with pytest.raises(TonpoError):
                raise exc_class("test")

    def test_gateway_connection_error_does_not_shadow_builtin(self):
        # The SDK must NOT export a class named 'ConnectionError'
        # which would shadow builtins.ConnectionError
        assert TonpoConnectionError is not builtins.ConnectionError
        assert TonpoConnectionError.__name__ == 'TonpoConnectionError'

    def test_builtin_connection_error_still_works(self):
        # After importing from SDK, builtins.ConnectionError is intact
        with pytest.raises(builtins.ConnectionError):
            raise builtins.ConnectionError("system network error")


class TestTonpoResponseError:

    def test_message_and_defaults(self):
        e = TonpoResponseError("bad gateway")
        assert str(e) == "bad gateway"
        assert e.status_code == 0
        assert e.raw == ""

    def test_with_status_and_raw(self):
        e = TonpoResponseError("server error", status_code=500, raw="Internal Server Error")
        assert e.status_code == 500
        assert e.raw == "Internal Server Error"

    def test_is_catchable_as_base(self):
        with pytest.raises(TonpoError) as exc_info:
            raise TonpoResponseError("oops", status_code=422)
        assert exc_info.value.status_code == 422
