"""Python server SDK for the Kraty game-events platform.

Targets the ``/server/v1`` surface: manual grants, IAP fulfilment,
inventory grant / revoke, wallet credit / debit, push-lobbies, and
unified player snapshots. Auto-retries on transient failures with
exponential backoff + jitter; preserves idempotency keys across
retries so the server's idempotency check dedupes replays.

**Server-side only.** Authenticated with a ``server_integration``
API key that can mint currency and items. Never embed in a game
client.

Example::

    from kraty_server_sdk import KratyServer

    kraty = KratyServer(api_key=os.environ["KRATY_SERVER_KEY"])

    # IAP fulfilment, idempotent on the receipt id:
    kraty.wallet.credit(
        "player_42",
        "gold",
        amount=500,
        reason="iap",
        source_ref_id="apple_receipt_abc",
        idempotency_key="apple_receipt_abc",
    )

    # Or a single mixed grant:
    kraty.grants.create(
        "player_42",
        idempotency_key="apple_receipt_abc",
        entries=[
            {"type": "currency", "currencyKey": "gold", "amount": 500},
            {"type": "item",     "itemKey": "starter_chest", "quantity": 1},
        ],
        source_ref_id="apple_receipt_abc",
    )
"""

from kraty_server_sdk.client import KratyAdminClient, RequestInfo, RetryConfig
from kraty_server_sdk.errors import KratyNetworkError, KratyServerError
from kraty_server_sdk.facade import KratyServer
from kraty_server_sdk.resources import (
    EventsClient,
    GrantsClient,
    HealthClient,
    InventoryClient,
    LeaderboardsClient,
    LobbiesClient,
    PlayersClient,
    WalletClient,
)
from kraty_server_sdk.webhook import verify_webhook

__version__ = "0.13.0"

__all__ = [
    "EventsClient",
    "GrantsClient",
    "HealthClient",
    "InventoryClient",
    "KratyServer",
    "KratyAdminClient",
    "KratyNetworkError",
    "KratyServerError",
    "LeaderboardsClient",
    "LobbiesClient",
    "PlayersClient",
    "RequestInfo",
    "RetryConfig",
    "WalletClient",
    "__version__",
    "verify_webhook",
]
