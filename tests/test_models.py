# tests/test_models.py
"""
Layer 1 — Model unit tests.
No network, no async — pure data transformation.
"""
import pytest
from tonpo.models import (
    TonpoConfig, UserCredentials, AccountCredentials,
    AccountInfo, Position, OrderResult,
    Quote, Tick, Candle, SymbolPrice,
)


# TonpoConfig
class TestTonpoConfig:

    def test_base_url_http(self):
        cfg = TonpoConfig(host="localhost", port=8080, use_ssl=False)
        assert cfg.base_url == "http://localhost:8080"

    def test_base_url_https(self):
        cfg = TonpoConfig(host="gateway.example.com", port=443, use_ssl=True)
        assert cfg.base_url == "https://gateway.example.com:443"

    def test_ws_url_plain(self):
        cfg = TonpoConfig(host="localhost", port=8080, use_ssl=False)
        assert cfg.ws_url == "ws://localhost:8080/ws"

    def test_ws_url_tls(self):
        cfg = TonpoConfig(host="gateway.example.com", port=443, use_ssl=True)
        assert cfg.ws_url == "wss://gateway.example.com:443/ws"

    def test_defaults(self):
        cfg = TonpoConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 8080
        assert cfg.use_ssl is False
        assert cfg.api_key_header == "X-API-Key"
        assert cfg.request_timeout == 30.0
        assert cfg.max_reconnect_attempts == 5


# ==================== AccountInfo ====================

class TestAccountInfo:

    def _full_dict(self):
        return {
            'login': 12345678,
            'name': 'Test Account',
            'server': 'ICMarkets-Demo',
            'balance': 10000.50,
            'equity': 10250.75,
            'margin': 500.0,
            'free_margin': 9750.75,
            'leverage': 100,
            'currency': 'USD',
            'profit': 250.25,
        }

    def test_from_dict_full(self):
        info = AccountInfo.from_dict(self._full_dict())
        assert info.login == 12345678
        assert info.name == 'Test Account'
        assert info.server == 'ICMarkets-Demo'
        assert info.balance == 10000.50
        assert info.equity == 10250.75
        assert info.margin == 500.0
        assert info.free_margin == 9750.75
        assert info.leverage == 100
        assert info.currency == 'USD'
        assert info.profit == 250.25

    def test_margin_level_normal(self):
        info = AccountInfo.from_dict(self._full_dict())
        # margin / equity * 100 = 500 / 10250.75 * 100
        expected = 500.0 / 10250.75 * 100
        assert abs(info.margin_level - expected) < 0.001

    def test_margin_level_zero_equity(self):
        d = self._full_dict()
        d['equity'] = 0
        info = AccountInfo.from_dict(d)
        assert info.margin_level == 0.0

    def test_from_dict_missing_fields_defaults(self):
        info = AccountInfo.from_dict({})
        assert info.login == 0
        assert info.name == ''
        assert info.currency == 'USD'
        assert info.profit == 0.0

    def test_login_is_int(self):
        info = AccountInfo.from_dict({'login': '12345678'})
        assert isinstance(info.login, int)

    def test_balance_is_float(self):
        info = AccountInfo.from_dict({'balance': '1000'})
        assert isinstance(info.balance, float)


# ==================== Position ====================

class TestPosition:

    def _position_dict(self):
        return {
            'ticket': 123456,
            'symbol': 'EURUSD',
            'side': 'buy',
            'volume': 0.1,
            'openPrice': 1.0850,
            'currentPrice': 1.0900,
            'profit': 50.0,
            'swap': -0.5,
            'commission': -0.7,
            'sl': 1.0800,
            'tp': 1.1000,
            'openTime': 1712345678,
            'comment': 'test',
        }

    def test_from_dict_full(self):
        p = Position.from_dict(self._position_dict())
        assert p.ticket == 123456
        assert p.symbol == 'EURUSD'
        assert p.side == 'buy'
        assert p.volume == 0.1
        assert p.open_price == 1.0850
        assert p.current_price == 1.0900
        assert p.profit == 50.0
        assert p.swap == -0.5
        assert p.commission == -0.7
        assert p.sl == 1.0800
        assert p.tp == 1.1000
        assert p.open_time == 1712345678
        assert p.comment == 'test'

    def test_sl_tp_none_when_missing(self):
        p = Position.from_dict({
            'ticket': 1, 'symbol': 'EURUSD', 'side': 'sell',
            'volume': 0.1, 'openPrice': 1.08, 'currentPrice': 1.09,
            'profit': 0, 'swap': 0, 'commission': 0,
        })
        assert p.sl is None
        assert p.tp is None

    def test_sl_tp_none_when_zero(self):
        # sl=0 / tp=0 should be treated as not set (falsy → None)
        p = Position.from_dict({
            'ticket': 1, 'symbol': 'EURUSD', 'side': 'buy',
            'volume': 0.1, 'openPrice': 1.08, 'currentPrice': 1.09,
            'profit': 0, 'swap': 0, 'commission': 0,
            'sl': 0, 'tp': 0,
        })
        assert p.sl is None
        assert p.tp is None

    def test_uses_camel_case_keys(self):
        # openPrice and currentPrice are camelCase from gateway
        p = Position.from_dict({'openPrice': 1.08, 'currentPrice': 1.09,
                                 'ticket': 1, 'symbol': 'X', 'side': 'buy',
                                 'volume': 0.1, 'profit': 0, 'swap': 0, 'commission': 0})
        assert p.open_price == 1.08
        assert p.current_price == 1.09

    def test_from_dict_defaults(self):
        p = Position.from_dict({})
        assert p.ticket == 0
        assert p.side == 'buy'
        assert p.comment == ''


# ==================== OrderResult ====================

class TestOrderResult:

    def test_success(self):
        r = OrderResult.from_dict({'ticket': 999, 'success': True})
        assert r.ticket == 999
        assert r.success is True
        assert r.error is None

    def test_failure_with_error(self):
        r = OrderResult.from_dict({'ticket': 0, 'success': False, 'error': 'Not enough margin'})
        assert r.success is False
        assert r.error == 'Not enough margin'

    def test_defaults(self):
        r = OrderResult.from_dict({})
        assert r.ticket == 0
        assert r.success is False
        assert r.error is None


# ==================== Quote ====================

class TestQuote:

    def test_spread(self):
        q = Quote(symbol='EURUSD', bid=1.08500, ask=1.08520, time=1712345678)
        assert q.spread == round(1.08520 - 1.08500, 5)

    def test_mid(self):
        q = Quote(symbol='EURUSD', bid=1.0850, ask=1.0852, time=1712345678)
        assert q.mid == round((1.0850 + 1.0852) / 2, 5)

    def test_spread_zero_when_equal(self):
        q = Quote(symbol='X', bid=1.0, ask=1.0, time=0)
        assert q.spread == 0.0


# ==================== SymbolPrice ====================

class TestSymbolPrice:

    def test_from_dict_flat(self):
        p = SymbolPrice.from_dict('EURUSD', {'bid': 1.0850, 'ask': 1.0852})
        assert p.symbol == 'EURUSD'
        assert p.bid == 1.0850
        assert p.ask == 1.0852

    def test_from_dict_nested_info(self):
        # gateway may wrap in 'info' key
        p = SymbolPrice.from_dict('GBPUSD', {'info': {'bid': 1.2700, 'ask': 1.2703}})
        assert p.bid == 1.2700
        assert p.ask == 1.2703

    def test_from_dict_empty(self):
        p = SymbolPrice.from_dict('USDJPY', {})
        assert p.bid == 0.0
        assert p.ask == 0.0


# ==================== Credentials ====================

class TestCredentials:

    def test_user_credentials(self):
        u = UserCredentials(gateway_user_id='uid-123', api_key='sk_abc')
        assert u.gateway_user_id == 'uid-123'
        assert u.api_key == 'sk_abc'

    def test_account_credentials_with_token(self):
        a = AccountCredentials(account_id='acc-123', auth_token='tok_xyz')
        assert a.account_id == 'acc-123'
        assert a.auth_token == 'tok_xyz'

    def test_account_credentials_no_token(self):
        a = AccountCredentials(account_id='acc-456')
        assert a.auth_token is None
