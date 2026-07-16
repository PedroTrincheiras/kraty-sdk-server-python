# kraty-server-sdk

Python server SDK for the [Kraty](https://kraty.io) game-events
platform, providing per-game server-side actions. Targets the `/server/v1`
surface: manual grants, IAP fulfilment, inventory grant / revoke,
wallet credit / debit, push-lobbies, and unified player snapshots.

> 📖 **Full reference + examples:** <https://kraty.io/docs/server-sdks/python>
>
> The docs site has the complete guide: IAP fulfilment patterns,
> every method, idempotency, retries, error handling. This README is
> just enough to get started.

> **Server-side only.** Authenticated with a `server_integration`
> API key that can mint currency and items. Never embed this SDK or
> its key in a client app. Use one of the Kraty client SDKs
> ([TypeScript](https://kraty.io/docs/sdks/typescript),
> [Flutter](https://kraty.io/docs/sdks/flutter),
> [Unity](https://kraty.io/docs/sdks/unity)) for game clients instead.

## Install

The package isn't on PyPI yet, so install directly from the public
GitHub repo against a tagged release.

```bash
# With uv (recommended):
uv add 'kraty-server-sdk @ git+https://github.com/PedroTrincheiras/kraty-sdk-server-python.git@v0.10.0'

# Or pip:
pip install 'git+https://github.com/PedroTrincheiras/kraty-sdk-server-python.git@v0.10.0'
```

Browse releases at
<https://github.com/PedroTrincheiras/kraty-sdk-server-python/releases>.
Once we publish to PyPI (v1.0) you'll be able to swap to
`uv add kraty-server-sdk`.

Requires Python 3.10+.

## Quickstart

```python
import os
from kraty_server_sdk import KratyServer

kraty = KratyServer(api_key=os.environ["KRATY_SERVER_KEY"])

# ── IAP fulfilment ──────────────────────────────────────────────
# Idempotency: pass the receipt id as the key, so replays return the
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

# Or a single mixed grant, items + currency in one atomic row:
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
kraty.grants        # create (manual mint) / ack
kraty.inventory     # grant / revoke
kraty.wallet        # credit / debit
kraty.lobbies       # push (pre-matched) / read
kraty.leaderboards  # submit_score (server-authoritative)
kraty.events        # report_progress (server-authoritative)
kraty.players       # get (unified snapshot)
kraty.health        # ping
```

## Server-authoritative scoring

These two methods write through the **trusted** server surface, so they
are **not** subject to the game's `acceptClientScores` gate. Use them
when scoring lives on your backend (anti-cheat, simulation, server-side
match results) rather than the game client.

```python
# Submit a score onto a score-ranked board.
# `context` boards: pass `segment` (the bucket value).
# `progression` boards: omit `segment` (server derives the bucket).
# unsegmented boards: `segment` is ignored.
result = kraty.leaderboards.submit_score(
    "player_42",
    "weekly_high_scores",
    12_500,
    segment="NA",
    idempotency_key="match_abc",
)
# {"leaderboardId": ..., "score": 12500, "rank": 3 | None}

# Push server-authoritative progress onto an in-flight event attempt.
# Returns {"attempt": {...}, "milestonesFired": [...]}.
progress = kraty.events.report_progress(
    "player_42",
    "summer_event",
    attempt_id,
    mode="increment",
    metric_value=50,
    idempotency_key="match_abc",
)
```

## Idempotency

Every POST is auto-stamped with an `idempotencyKey` (UUID4) if you
don't supply one, but for server-side fulfilment you almost always
want to **provide your own** key (typically the IAP receipt id or
your internal fulfilment record id). That way:

- Replays of the same fulfilment (network retries, crash recovery,
  webhook redelivery) return the **original** grant.
- A misconfigured retry that ships a different body returns
  `KratyServerError` with `.is_idempotency_conflict == True`, so
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
        # Same receipt, different payload: investigate before retry.
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
        ...  # burst limit; retry budget already exhausted
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
| `kraty.leaderboards` | `submit_score(external_player_id, key, value, *, segment=None, idempotency_key=None)` → `POST /server/v1/leaderboards/:key/score` |
| `kraty.events` | `report_progress(external_player_id, event_key, attempt_id, *, mode, metric_value=None, metrics=None, occurred_at=None, idempotency_key=None)` → `POST /server/v1/players/:externalId/events/:eventKey/attempts/:attemptId/progress` |
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

Tests use `respx` to mock httpx, so there is no real network IO. Useful as a
worked example when you're writing tests for your own fulfilment
pipeline.
