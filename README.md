# tonpo-py

[![PyPI version](https://img.shields.io/pypi/v/tonpo.svg)](https://pypi.org/project/tonpo/)
[![Python](https://img.shields.io/pypi/pyversions/tonpo.svg)](https://pypi.org/project/tonpo/)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)

Official Python SDK for the **Tonpo API**. Easily integrate MetaTrader 5 into your Python applications.

---

## What is Tonpo?

Tonpo is a cloud API that gives your application a direct connection to MetaTrader 5. Send your MT5 credentials once, and trade through a simple Python interface — no Windows server, no MT5 installation, no infrastructure to manage.

```
Your Application
      │
      │  HTTPS / WSS
      ▼
Tonpo Gateway
      │
      │
      ▼
MT5 Terminal → Broker
        │
        ▼
  Your Broker
  (ICMarkets, XM, FBS, ...)
```

You only interact with the top — your app calls the SDK, Tonpo handles everything below.

---

## Installation

```bash
pip install tonpo
```

Install the latest development version:

```bash
pip install git+https://github.com/TonpoLabs/tonpo-py.git
```

Clone and install locally for development:

```bash
git clone https://github.com/TonpoLabs/tonpo-py.git
cd tonpo-py
pip install -e ".[dev]"
```

**Requirements:** Python 3.10+

---

## Quick Start

```python
import asyncio
from tonpo import TonpoClient, TonpoConfig

config = TonpoConfig(
    host="gateway.tonpo.io",
    port=443,
    use_ssl=True,
)

async def main():
    # Step 1 — Create a Tonpo user account (once per user)
    async with TonpoClient.admin(config) as client:
        user = await client.create_user()
        print(f"api_key: {user.api_key}")          # save this
        print(f"user_id: {user.gateway_user_id}")   # save this

    # Step 2 — Connect an MT5 account (once per MT5 account)
    async with TonpoClient.for_user(config, user.api_key) as client:
        account = await client.create_account(
            mt5_login="123456789",
            mt5_password="YourMT5Password",
            mt5_server="FBS-Demo",
        )
        print(f"account_id: {account.account_id}")  # save this

        # Wait for MT5 to log in — takes 2–4 minutes on first connect
        await client.wait_for_active(account.account_id, timeout=180)
        print("MT5 connected!")

    # Step 3 — Trade (api_key + account_id is all you need from here)
    async with TonpoClient.for_user(config, user.api_key) as client:
        info = await client.get_account_info()
        print(f"Balance: {info.balance} {info.currency}")

        result = await client.place_market_buy("EURUSD", volume=0.1, sl=1.0800, tp=1.1000)
        print(f"Order placed: ticket={result.ticket}")

asyncio.run(main())
```

---

## How It Works

Tonpo separates setup from trading. You go through setup once per user and once per MT5 account. After that, all you need are three values stored in your database.

```
Setup (run once)

create_user()       →  api_key + gateway_user_id   (save to DB)
create_account()    →  account_id                   (save to DB)
wait_for_active()   →  MT5 is logged in, ready to trade

Every request after that

for_user(api_key)   →  identifies and authenticates the user
account_id          →  tells Tonpo which MT5 account to act on

MT5 login, password, server — never needed again after setup.
```

Store only these three values per user in your database:

| Field | Description |
|---|---|
| `tonpo_api_key` | Authenticates every request |
| `tonpo_user_id` | User identity on Tonpo |
| `tonpo_account_id` | Identifies which MT5 account to act on |

---

## Configuration

```python
from tonpo import TonpoConfig

config = TonpoConfig(
    host="gateway.tonpo.io",      # Tonpo gateway hostname
    port=443,                      # 443 for SSL (default)
    use_ssl=True,                  # always True in production
    api_key_header="X-API-Key",    # header name (default is correct)
    connect_timeout=10.0,          # seconds to establish connection
    request_timeout=30.0,          # seconds to wait for a response
    ws_reconnect_delay=5.0,        # seconds between WebSocket reconnect attempts
    max_reconnect_attempts=5,      # max reconnects before raising an error
)
```

---

## Client Modes

### Admin client — no authentication required

Used only for `health_check()` and `create_user()`.

```python
async with TonpoClient.admin(config) as client:
    healthy = await client.health_check()
    user    = await client.create_user()
```

### User client — authenticated

Used for all trading and account operations.

```python
async with TonpoClient.for_user(config, api_key="your-api-key") as client:
    info = await client.get_account_info()
```

### Manual lifecycle

```python
client = TonpoClient(config, api_key="your-api-key")
await client.start()
try:
    await client.get_account_info()
finally:
    await client.stop()
```

---

## API Reference

### Health

```python
healthy = await client.health_check()  # → bool
```

---

### User Management

```python
# Create a new Tonpo user — no auth required
user = await client.create_user()
# user.gateway_user_id  — store in your DB
# user.api_key          — store in your DB (shown once — save immediately)
```

---

### Account Lifecycle

```python
# Connect an MT5 account to Tonpo
account = await client.create_account(
    mt5_login="105745233",
    mt5_password="password",
    mt5_server="FBS-Demo",
    region="eu",          # optional — route to a specific region
)
# account.account_id — store in your DB

# Wait for MT5 to become active (logged in to broker)
# Default timeout is 180s — first connect takes 2–4 minutes
await client.wait_for_active(account.account_id, timeout=180)

# Check status manually
status = await client.get_account_status(account.account_id)
# status["status"]     — "active" | "connecting" | "paused" | "login_failed" | "deleted"
# status["last_error"] — error message if status is "login_failed"

# List all accounts for this user
accounts = await client.get_accounts()  # → List[dict]

# Pause / resume (blocks new orders while paused — MT5 stays connected)
await client.pause_account(account.account_id)
await client.resume_account(account.account_id)

# Remove account permanently
await client.delete_account(account.account_id)
```

---

### Account Information

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
# info.currency     → str    ("USD", "EUR", ...)
# info.profit       → float
# info.margin_level → float  (equity / margin * 100)
```

---

### Positions

```python
positions = await client.get_positions()
for p in positions:
    print(p.ticket, p.symbol, p.side, p.volume, p.profit)

# Close a position (full or partial)
result = await client.close_position(ticket=123456)
result = await client.close_position(ticket=123456, volume=0.05)  # partial close

# Modify SL / TP
result = await client.modify_position(ticket=123456, sl=1.0800, tp=1.1000)
```

---

### Orders

```python
# Market orders
result = await client.place_market_buy("EURUSD",  volume=0.1)
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
    sl=1.0800,      # absolute stop loss price
    tp=1.1000,      # absolute take profit price
    comment="bot",  # visible in MT5 order history
    magic=12345,    # magic number — identifies your bot's orders in MT5
)

# result.ticket  → int         — MT5 ticket number
# result.success → bool
# result.error   → str | None  — broker error message on failure
```

---

### Market Data (REST)

```python
price = await client.get_symbol_price("EURUSD")
# price.symbol → "EURUSD"
# price.bid    → float
# price.ask    → float
# Falls back to WebSocket price cache automatically if REST returns zeros
```

---

### Real-Time Data (WebSocket)

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

# Subscribe to symbols and start receiving data
await client.subscribe(["EURUSD", "GBPUSD"])

# Keep the event loop alive
await asyncio.sleep(3600)

# Unsubscribe and check connection
await client.unsubscribe(["GBPUSD"])
alive = await client.ping_ws()  # → bool
```

---

## Models

| Model | Key fields |
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

## Exceptions

All exceptions inherit from `TonpoError`.

```python
from tonpo import (
    TonpoError,              # base — catch-all
    NotStartedError,         # client used before start() or outside async with
    AuthenticationError,     # invalid or revoked API key
    AccountNotFoundError,    # account_id does not exist
    AccountLoginFailedError, # MT5 credentials rejected by broker
    AccountTimeoutError,     # account did not become active within timeout
    OrderError,              # order placement, close, or modify failed
    TonpoConnectionError,    # HTTP or WebSocket connection failed
    SubscriptionError,       # WebSocket market data subscription failed
    TonpoResponseError,      # unexpected HTTP response (.status_code, .raw)
)
```

> `TonpoConnectionError` is intentionally not named `ConnectionError` — that would shadow Python's built-in `builtins.ConnectionError`.

### Error handling

```python
from tonpo import (
    TonpoClient,
    AccountLoginFailedError,
    AccountTimeoutError,
    TonpoConnectionError,
    AuthenticationError,
    TonpoError,
)

# Account setup
try:
    await client.wait_for_active(account.account_id, timeout=180)
except AccountLoginFailedError as e:
    print(f"Wrong MT5 credentials: {e}")
    await client.delete_account(account.account_id)
except AccountTimeoutError as e:
    print(f"MT5 took too long to connect: {e}")

# Trading
try:
    result = await client.place_market_buy("EURUSD", volume=0.1)
except AuthenticationError:
    print("API key invalid — re-create the user")
except TonpoConnectionError:
    print("Cannot reach Tonpo — check your internet connection")
except TonpoError as e:
    print(f"Tonpo error: {e}")
```

---

## Example — Telegram Trading Bot

A common use case: each Telegram user connects their own MT5 account, and your bot places trades on their behalf.

```python
from tonpo import TonpoClient, TonpoConfig, AccountLoginFailedError, AccountTimeoutError

config = TonpoConfig(host="gateway.tonpo.io", port=443, use_ssl=True)

#  Registration
# Called once when a user submits their MT5 credentials.

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

    # MT5 credentials are never needed again — store only these three values
    db.save(
        telegram_id      = telegram_id,
        tonpo_api_key    = user.api_key,
        tonpo_user_id    = user.gateway_user_id,
        tonpo_account_id = account.account_id,
    )

# Place a trade 
async def place_buy(telegram_id, symbol, volume):
    row = db.get(telegram_id=telegram_id)
    async with TonpoClient.for_user(config, row.tonpo_api_key) as c:
        result = await c.place_market_buy(symbol, volume=volume)
        return result.ticket

# Check balance
async def get_balance(telegram_id):
    row = db.get(telegram_id=telegram_id)
    async with TonpoClient.for_user(config, row.tonpo_api_key) as c:
        info = await c.get_account_info()
        return info.balance, info.currency
```
## License

Proprietary — All rights reserved. © Tonpo. Unauthorised copying, distribution, or use is strictly prohibited.
