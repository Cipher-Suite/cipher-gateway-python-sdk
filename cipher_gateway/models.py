# cipher_gateway/models.py
"""
CipherGateway SDK data models.
All data returned from the gateway is typed through these classes.
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any


# ==================== Configuration ====================

@dataclass
class GatewayConfig:
    """Gateway connection configuration"""
    host: str = "localhost"
    port: int = 8080
    use_ssl: bool = False
    api_key_header: str = "X-API-Key"
    connect_timeout: float = 10.0
    request_timeout: float = 30.0
    ws_reconnect_delay: float = 5.0
    max_reconnect_attempts: int = 5

    @property
    def base_url(self) -> str:
        protocol = "https" if self.use_ssl else "http"
        return f"{protocol}://{self.host}:{self.port}"

    @property
    def ws_url(self) -> str:
        protocol = "wss" if self.use_ssl else "ws"
        return f"{protocol}://{self.host}:{self.port}/ws"


# ==================== Auth ====================

@dataclass
class UserCredentials:
    """
    Returned by create_user().
    Store gateway_user_id and api_key — that's all the bot needs.
    """
    gateway_user_id: str
    api_key: str


@dataclass
class AccountCredentials:
    """
    Returned by create_account().
    Store account_id — paired with api_key this routes all future requests.
    """
    account_id: str
    auth_token: Optional[str] = None


# ==================== Account ====================

@dataclass
class AccountInfo:
    """MT5 account information"""
    login: int
    name: str
    server: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    leverage: int
    currency: str
    profit: float

    @property
    def margin_level(self) -> float:
        return (self.margin / self.equity * 100) if self.equity > 0 else 0.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AccountInfo':
        return cls(
            login=int(data.get('login', 0)),
            name=data.get('name', ''),
            server=data.get('server', ''),
            balance=float(data.get('balance', 0)),
            equity=float(data.get('equity', 0)),
            margin=float(data.get('margin', 0)),
            free_margin=float(data.get('free_margin', 0)),
            leverage=int(data.get('leverage', 0)),
            currency=data.get('currency', 'USD'),
            profit=float(data.get('profit', 0)),
        )


# ==================== Trading ====================

@dataclass
class Position:
    """Open trading position"""
    ticket: int
    symbol: str
    side: str       # 'buy' or 'sell'
    volume: float
    open_price: float
    current_price: float
    profit: float
    swap: float
    commission: float
    sl: Optional[float] = None
    tp: Optional[float] = None
    open_time: Optional[int] = None
    comment: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Position':
        return cls(
            ticket=int(data.get('ticket', 0)),
            symbol=data.get('symbol', ''),
            side=data.get('side', 'buy'),
            volume=float(data.get('volume', 0)),
            open_price=float(data.get('openPrice', 0)),
            current_price=float(data.get('currentPrice', 0)),
            profit=float(data.get('profit', 0)),
            swap=float(data.get('swap', 0)),
            commission=float(data.get('commission', 0)),
            sl=float(data['sl']) if data.get('sl') else None,
            tp=float(data['tp']) if data.get('tp') else None,
            open_time=data.get('openTime'),
            comment=data.get('comment', ''),
        )


@dataclass
class OrderResult:
    """Result of a placed, closed or modified order"""
    ticket: int
    success: bool
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OrderResult':
        return cls(
            ticket=int(data.get('ticket', 0)),
            success=bool(data.get('success', False)),
            error=data.get('error'),
        )


# ==================== Market Data ====================

@dataclass
class Quote:
    """Real-time bid/ask quote"""
    symbol: str
    bid: float
    ask: float
    time: int

    @property
    def spread(self) -> float:
        return round(self.ask - self.bid, 5)

    @property
    def mid(self) -> float:
        return round((self.bid + self.ask) / 2, 5)


@dataclass
class Tick:
    """Raw tick data"""
    symbol: str
    bid: float
    ask: float
    last: float
    volume: int
    time: int


@dataclass
class Candle:
    """OHLCV candle"""
    symbol: str
    timeframe: str
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    complete: bool


@dataclass
class SymbolPrice:
    """Current price for a symbol"""
    symbol: str
    bid: float
    ask: float

    @classmethod
    def from_dict(cls, symbol: str, data: Dict[str, Any]) -> 'SymbolPrice':
        info = data.get('info', data)
        return cls(
            symbol=symbol,
            bid=float(info.get('bid', 0)),
            ask=float(info.get('ask', 0)),
        )
