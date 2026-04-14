# tonpo-py

[![PyPI version](https://img.shields.io/pypi/v/tonpo.svg)](https://pypi.org/project/tonpo/)
[![Python](https://img.shields.io/pypi/pyversions/tonpo.svg)](https://pypi.org/project/tonpo/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Official Python SDK for the **Tonpo MT5 Gateway (TMG)** — a self-hosted bridge between your application and MetaTrader 5.

Built and maintained by [TonpoLabs](https://cipherbridge.cloud).

---

### What is TMG?

The Tonpo MT5 Gateway is a self-hosted Rust server that manages MT5 terminal connections through the TonpoBridge (TMB) C++ bridge. Instead of routing through third-party cloud APIs, TMG runs on your own infrastructure — giving you full control over latency, cost, and data.

```
Your App (Python)
      │
      │  HTTPS / WSS
      ▼
TMG  (Rust — your server)
      │
      │  WebSocket
      ▼
TMB  (C++ DLL + MQL5 EA)
      │
      ▼
MT5 Terminal → Broker
```

This SDK handles all communication with TMG so you never write raw HTTP calls.

---

### Installation

```bash
pip install tonpo
```

Or install the latest development version directly from GitHub:

```bash
pip install git+https://github.com/TonpoLabs/tonpo-py.git
```

Or clone and install locally for development:

```bash
git clone https://github.com/TonpoLabs/tonpo-py.git
cd tonpo
pip install -e ".[dev]"
```

**Requirements:** Python 3.10+

---

### Quick Start

```python
import asyncio
from tonpo import TonpoClient, TonpoConfig

config = TonpoConfig(
    host="gateway.yourdomain.com",
    port=443,
    use_ssl=True,
)

async def main():
    # 1. Create a tonpo user — do this once per user, store the credentials
    async with TonpoClient.admin(config) as client:
        user_creds = await client.create_user()
        print(f"api_key:    {user_creds.api_key}")
        print(f"user_id:    {user_creds.gateway_user_id}")

    # 2. Provision an MT5 account — do this once per MT5 account
    async with TonpoClient.for_user(config, user_creds.api_key) as client:
        account = await client.create_account(
            mt5_login="12345678",
            mt5_password="YourMT5Password",
            mt5_server="ICMarkets-Demo",
        )
        print(f"account_id: {account.account_id}")

        # Wait for MT5 to connect — up to 180s (Windows VPS cold start takes 2–4 min)
        await client.wait_for_active(account.account_id, timeout=180)
        print("MT5 connected!")

    # 3. Trade — use api_key + account_id from now on, credentials never needed again
    async with TonpoClient.for_user(config, user_creds.api_key) as client:
        info = await client.get_account_info()
        print(f"Balance: {info.balance} {info.currency}")

        result = await client.place_market_buy("EURUSD", volume=0.1, sl=1.0800, tp=1.1000)
        print(f"Order placed: ticket={result.ticket}")

asyncio.run(main())
```

---

### Core Concept — Credential Flow

TMG owns your MT5 credentials. The SDK reflects this:

```
Step 1 — Register (one time per user)
  create_user()        → returns api_key + tonpo_user_id  (store these)
  create_account()     → returns account_id                 (store this)
  wait_for_active()    → confirms MT5 is connected

Step 2 — Every request after that
  for_user(api_key)    → authenticates the user
  account_id           → tells TMG which MT5 account to act on

MT5 login, password, server — never needed again after Step 1.
```

Store only these three values per user in your database:

| Field | Description |
|---|---|
| `tonpo_user_id` | Identifies the user on the gateway |
| `tonpo_api_key` | Authenticates every request |
| `tonpo_account_id` | Identifies which MT5 account to act on |

---

### Configuration

```python
from tonpo import TonpoConfig

config = TonpoConfig(
    host="gateway.yourdomain.com",  # CMG hostname or IP
    port=443,                        # 443 for SSL, 8080 for plain HTTP
    use_ssl=True,                    # Must match your nginx/proxy setup
    api_key_header="X-API-Key",      # Header name CMG expects (default is fine)
    connect_timeout=10.0,            # Seconds to establish connection
    request_timeout=30.0,            # Seconds to wait for a response
    ws_reconnect_delay=5.0,          # Seconds between WebSocket reconnect attempts
    max_reconnect_attempts=5,        # Max WebSocket reconnect attempts before error
)
```

---

### Client Modes

#### Admin client — no authentication required

Used only for `health_check()` and `create_user()`.

```python
async with TonpoClient.admin(config) as client:
    healthy    = await client.health_check()
    user_creds = await client.create_user()
```

#### User client — authenticated

Used for all trading and account operations.

```python
async with TonpoClient.for_user(config, api_key="your-api-key") as client:
    info = await client.get_account_info()
```

---

### API Reference

#### Health

```python
healthy = await client.health_check()  # → bool
```

#### User Management

```python
# Create a new tonpo user (admin client, no auth required)
user_creds = await client.create_user()
# user_creds.tonpo_user_id  — store in DB
# user_creds.api_key           — store in DB
```

### Account Lifecycle

```python
# Provision a new MT5 account on CMG
account = await client.create_account(
    mt5_login="12345678",
    mt5_password="password",
    mt5_server="ICMarkets-Demo",
    region="eu",        # optional — route to a specific node region
)
# account.account_id  — store in DB

# Wait for MT5 connection to become active
# timeout=180 — Windows VPS cold start takes 2–4 minutes
await client.wait_for_active(account.account_id, timeout=180)

# Check status manually
status = await client.get_account_status(account.account_id)
# status["status"]     — "active", "connecting", "login_failed", "deleted"
# status["last_error"] — error message if login_failed

# List all accounts for this user
accounts = await client.get_accounts()

# Pause / resume trading (keeps MT5 connected, blocks new orders)
await client.pause_account(account.account_id)
await client.resume_account(account.account_id)

# Remove account from CMG permanently
await client.delete_account(account.account_id)
```

#### Account Information

```python
info = await client.get_account_info()
# info.login        → int
# info.name         → str
# info.server       → str
# info.balance      → float
# info.equity       → float
# info.margin       → float
# info.free_margin  → float
# info.leverage     → int
# info.currency     → str  ("USD", "EUR", ...)
# info.profit       → float
# info.margin_level → float  (computed property — margin/equity %)
```

### Positions

```python
# Get all open positions
positions = await client.get_positions()
for p in positions:
    print(p.ticket, p.symbol, p.side, p.volume, p.profit)

# Close a position (full or partial)
result = await client.close_position(ticket=123456)
result = await client.close_position(ticket=123456, volume=0.05)  # partial close

# Modify SL/TP on an open position
result = await client.modify_position(ticket=123456, sl=1.0800, tp=1.1000)
```

#### Orders

```python
# Market orders
result = await client.place_market_buy("EURUSD", volume=0.1)
result = await client.place_market_sell("GBPUSD", volume=0.2, sl=1.2500, tp=1.2200)

# Limit orders
result = await client.place_limit_buy("EURUSD",  volume=0.1, price=1.0750)
result = await client.place_limit_sell("EURUSD", volume=0.1, price=1.1050)

# Stop orders
result = await client.place_stop_buy("EURUSD",  volume=0.1, price=1.0950)
result = await client.place_stop_sell("EURUSD", volume=0.1, price=1.0700)

# All order methods accept optional parameters
result = await client.place_market_buy(
    symbol="EURUSD",
    volume=0.1,
    sl=1.0800,       # stop loss price
    tp=1.1000,       # take profit price
    comment="bot",   # order comment visible in MT5
    magic=12345,     # magic number for identifying bot orders
)

# OrderResult fields
# result.ticket   → int       (MT5 ticket number)
# result.success  → bool
# result.error    → str|None  (broker error message on failure)
```

### Market Data (REST)

```python
price = await client.get_symbol_price("EURUSD")
# price.symbol  → "EURUSD"
# price.bid     → float
# price.ask     → float
# Falls back to WebSocket price cache if REST returns zeros
```

#### Real-Time Data (WebSocket)

```python
# Register callbacks before subscribing
def on_tick(tick):
    print(f"{tick.symbol}  bid={tick.bid}  ask={tick.ask}")

async def on_position_update(position):
    print(f"Position {position.ticket}: profit={position.profit}")

client.ws.on_tick("EURUSD", on_tick)
client.ws.on_position(on_position_update)
client.ws.on_candle("EURUSD", "H1", lambda c: print(f"H1 close={c.close}"))
client.ws.on_order_result(lambda r: print(f"Order {r.ticket} ok={r.success}"))
client.ws.on_account(lambda a: print(f"Balance={a.balance} {a.currency}"))

# Subscribe — this starts the WebSocket connection
await client.subscribe(["EURUSD", "GBPUSD"])

# Keep the event loop running to receive data
await asyncio.sleep(3600)

# Unsubscribe and ping
await client.unsubscribe(["GBPUSD"])
alive = await client.ping_ws()  # → bool
```

---

### Models

| Model | Fields |
|---|---|
| `TonpoConfig` | `host`, `port`, `use_ssl`, `api_key_header`, `connect_timeout`, `request_timeout`, `ws_reconnect_delay`, `max_reconnect_attempts` |
| `UserCredentials` | `gateway_user_id`, `api_key` |
| `AccountCredentials` | `account_id`, `auth_token` |
| `AccountInfo` | `login`, `name`, `server`, `balance`, `equity`, `margin`, `free_margin`, `leverage`, `currency`, `profit`, `margin_level` |
| `Position` | `ticket`, `symbol`, `side`, `volume`, `open_price`, `current_price`, `profit`, `swap`, `commission`, `sl`, `tp`, `open_time`, `comment` |
| `OrderResult` | `ticket`, `success`, `error` |
| `SymbolPrice` | `symbol`, `bid`, `ask` |
| `Tick` | `symbol`, `bid`, `ask`, `last`, `volume`, `time` |
| `Quote` | `symbol`, `bid`, `ask`, `time`, `spread`, `mid` |
| `Candle` | `symbol`, `timeframe`, `time`, `open`, `high`, `low`, `close`, `volume`, `complete` |

---

### Exceptions

All exceptions inherit from `TonpoError`.

```python
from tonpo import (
    TonpoError,        # base — catch-all for any SDK error
    NotStartedError,           # client used before start() / outside async with
    AuthenticationError,       # invalid or missing API key
    AccountNotFoundError,      # account_id does not exist on gateway
    AccountLoginFailedError,   # MT5 credentials rejected by broker
    AccountTimeoutError,       # account did not become active in time
    OrderError,                # order placement/close/modify failed
    TonpoConnectionError,    # HTTP or WebSocket connection to gateway failed
    SubscriptionError,         # WebSocket market-data subscription failed
    TonpoResponseError,      # unexpected HTTP response (.status_code, .raw)
)
```

> **Note:** The exception is named `TonpoConnectionError`, not `ConnectionError`,
> to avoid shadowing Python's built-in `builtins.ConnectionError`.

Example error handling:

```python
from tonpo import (
    TonpoClient,
    AccountLoginFailedError,
    AccountTimeoutError,
    GatewayConnectionError,
    AuthenticationError,
    TonpoError,
)

# Account provisioning
try:
    await client.wait_for_active(account.account_id, timeout=180)
except AccountLoginFailedError as e:
    print(f"Wrong MT5 credentials: {e}")
except AccountTimeoutError as e:
    print(f"MT5 took too long to connect: {e}")

# Trading
try:
    result = await client.place_market_buy("EURUSD", volume=0.1)
except AuthenticationError:
    print("API key invalid — re-register the user")
except TonpoConnectionError:
    print("Cannot reach gateway — check server")
except TonpoError as e:
    print(f"Gateway error: {e}")
```

---

### Usage in a Telegram Bot

```python
from tonpo import (
    TonpoClient,
    TonpoConfig,
    AccountLoginFailedError,
    AccountTimeoutError,
)

config = TonpoConfig(host="gateway.yourdomain.com", port=443, use_ssl=True)

# ── Registration handler — called once when user enters MT5 credentials ──────
async def register_user(telegram_id, mt5_login, mt5_password, mt5_server):
    async with TonpoClient.admin(config) as c:
        user = await c.create_user()

    async with TonpoClient.for_user(config, user.api_key) as c:
        account = await c.create_account(mt5_login, mt5_password, mt5_server)
        try:
            await c.wait_for_active(account.account_id, timeout=180)
        except AccountLoginFailedError:
            await c.delete_account(account.account_id)
            raise

    # Save only these three — credentials never needed again
    db.save(
        telegram_id        = telegram_id,
        tonpo_api_key    = user.api_key,
        tonpo_account_id = account.account_id,
    )

# ── Trade handler — called on every trade command ────────────────────────────
async def place_buy(telegram_id, symbol, volume):
    row = db.get(telegram_id=telegram_id)
    async with TonpoClient.for_user(config, row.gateway_api_key) as c:
        result = await c.place_market_buy(symbol, volume=volume)
        return result.ticket
```

---

### Project Structure

```
tonpo-py/          ← GitHub repo root
├── pyproject.toml              ← packaging metadata (pip reads this)
├── setup.py                    ← minimal shim for legacy tools
├── MANIFEST.in                 ← files to include in source distribution
├── LICENSE
├── README.md
├── CHANGELOG.md
├── .gitignore
├── .github/
│   └── workflows/
│       └── publish.yml         ← auto-publishes to PyPI on git tag
└── tonpo/             ← the installable package
    ├── __init__.py             ← public API + __version__
    ├── client.py               ← TonpoClient (main entry point)
    ├── models.py               ← all dataclasses
    ├── exceptions.py           ← exception hierarchy
    ← transport.py              ← HTTP layer (httpx wrapper)
    ├── websocket.py            ← WebSocket layer (real-time + reconnection)
    └── py.typed                ← PEP 561 marker (empty file — enables IDE type hints)
```

#### Publishing a new release

```bash
# Bump version in pyproject.toml and CHANGELOG.md, then:
git add .
git commit -m "Release v1.0.1"
git tag v1.0.1
git push origin main
git push origin v1.0.1
# GitHub Actions builds and uploads to PyPI automatically
```

---

### Changelog

### v1.0.0 — 2026-04-10

- Initial release
- `TonpoClient` with admin and user factory methods
- Full account lifecycle: `create_account`, `wait_for_active`, `delete_account`, `pause_account`, `resume_account`
- All order types: market, limit, stop
- Position management: `get_positions`, `close_position`, `modify_position`
- WebSocket real-time data with auto-reconnection: ticks, quotes, candles, positions, order results
- Typed models for all gateway responses
- `GatewayConnectionError` — correctly named to avoid shadowing `builtins.ConnectionError`

---

### License

MIT — see [LICENSE](LICENSE).
