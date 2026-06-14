# kraty-server-sdk

Python server SDK for the Kraty game-events platform — per-game
server-side actions. Targets the `/server/v1` surface: manual
grants, IAP fulfilment,
inventory grant / revoke, wallet credit / debit, push-lobbies, and
unified player snapshots.

> **Server-side only.** Authenticated with a `server_integration`
> API key that can mint currency and items. Never embed this SDK
> or its key in a client app — use one of the Kraty client SDKs
> (TypeScript / Flutter / Unity) for game clients instead.

## Install

```bash
uv add kraty-server-sdk
# or
pip install kraty-server-sdk
```

Requires Python 3.10+.

## Quickstart

```python
import os
from kraty_server_sdk import KratyServer

kraty = KratyServer(api_key=os.environ["KRATY_SERVER_KEY"])

# ── IAP fulfilment ──────────────────────────────────────────────
# Idempotency: pass the receipt id as the key — replays return the
# SAME grant without a duplicate mint.
kraty.wallet.credit(
    "player_42",
    "gold",
    amount=500,
    reason="iap",
    source_ref_id="apple_receipt_abc",
    idempotency_key="apple_receipt_abc",
)

kraty.inventory.grant(
    "player_42",
    "starter_chest",
    quantity=1,
    reason="iap",
    idempotency_key="apple_receipt_abc",
)

# Or a single mixed grant — items + currency in one atomic row:
kraty.grants.create(
    "player_42",
    idempotency_key="apple_receipt_abc",
    entries=[
        {"type": "currency", "currencyKey": "gold", "amount": 500},
        {"type": "item",     "itemKey": "starter_chest", "quantity": 1},
    ],
    source_kind="api",
    source_ref_id="apple_receipt_abc",
)

kraty.close()  # or use as a context manager:
# with KratyServer(api_key=...) as kraty:
#     ...
```

## Resource clients

```python
kraty.grants      # create (manual mint) / ack
kraty.inventory   # grant / revoke
kraty.wallet      # credit / debit
kraty.lobbies     # push (pre-matched) / read
kraty.players     # get (unified snapshot)
kraty.health      # ping
```

## Idempotency

Every POST is auto-stamped with an `idempotencyKey` (UUID4) if you
don't supply one — but for server-side fulfilment you almost always
want to **provide your own** key (typically the IAP receipt id or
your internal fulfilment record id). That way:

- Replays of the same fulfilment (network retries, crash recovery,
  webhook redelivery) return the **original** grant.
- A misconfigured retry that ships a different body returns
  `KratyServerError` with `.is_idempotency_conflict == True` — so
  duplicate mints can't sneak through silently.

```python
from kraty_server_sdk import KratyServerError

try:
    kraty.wallet.credit(
        "p", "gold",
        amount=500,
        idempotency_key=receipt_id,
    )
except KratyServerError as err:
    if err.is_idempotency_conflict:
        # Same receipt, different payload — investigate before retry.
        alert_ops(receipt_id=receipt_id)
    else:
        raise
```

## Retries

Every transient failure (`408` / `425` / `429` / `5xx` + network
crash) is retried with exponential backoff + jitter, preserving the
same `idempotencyKey` across attempts so the server's idempotency
check dedupes the replay.

```python
from kraty_server_sdk import KratyServer, RetryConfig

kraty = KratyServer(
    api_key="...",
    retry=RetryConfig(
        attempts=5,
        initial_delay=0.5,
        max_delay=30.0,
        jitter=0.25,
    ),
)
```

`Retry-After` headers (used by 429 responses) are honored.

## Error handling

```python
from kraty_server_sdk import KratyServerError, KratyNetworkError

try:
    kraty.grants.create("player_42", ...)
except KratyServerError as err:
    if err.is_idempotency_conflict:
        ...  # duplicate fulfilment with different body
    elif err.is_not_found:
        ...  # player or item doesn't exist in this game
    elif err.is_forbidden:
        ...  # wrong key for this game/studio
    elif err.is_rate_limited:
        ...  # burst limit — retry budget already exhausted
except KratyNetworkError as err:
    ...  # backend unreachable; err.original_cause has the underlying exception
```

## Telemetry

```python
def on_request(info):
    metrics.timing(f"kraty_server.{info.url}", info.duration_ms or 0)
    if not info.ok:
        metrics.increment(f"kraty_server.error.{info.status}")

kraty = KratyServer(api_key="...", on_request=on_request)
```

Fires once per HTTP attempt, including retries.

## Resource reference

| Client | Methods |
|---|---|
| `kraty.grants` | `create(external_player_id, idempotency_key, entries, ...)`, `ack(external_player_id, grant_id, ...)` |
| `kraty.inventory` | `grant(external_player_id, item_key, quantity, ...)`, `revoke(external_player_id, item_key, quantity, ...)` |
| `kraty.wallet` | `credit(external_player_id, economy_key, amount, ...)`, `debit(external_player_id, economy_key, amount, ...)` |
| `kraty.lobbies` | `push(game_id, event_key, key, external_player_ids, ...)`, `read(game_id, lobby_id)` |
| `kraty.players` | `get(external_player_id)` |
| `kraty.health` | `ping()` |

## Development

```bash
# Install dev dependencies (httpx, pytest, respx, ruff, mypy)
uv sync --dev

# Run tests
uv run pytest

# Lint + typecheck
uv run ruff check src tests
uv run mypy src
```

Tests use `respx` to mock httpx — no real network IO. Useful as a
worked example when you're writing tests for your own fulfilment
pipeline.
