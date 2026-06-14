"""Convenience facade — instantiate one :class:`KratyServer` instead
of wiring up :class:`KratyAdminClient` + each resource client by
hand.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from kraty_server_sdk.client import DEFAULT_BASE_URL, KratyAdminClient, RetryConfig
from kraty_server_sdk.resources import (
    GrantsClient,
    HealthClient,
    InventoryClient,
    LobbiesClient,
    MigrateClient,
    PlayersClient,
    WalletClient,
)

if TYPE_CHECKING:
    import httpx

    from kraty_server_sdk.client import RequestInfo


class KratyServer:
    """Convenience facade for the ``/server/v1`` server surface.

    Instantiate one ``KratyServer`` per studio/game backend service —
    all resource clients share the same underlying HTTP client
    (connection pool, retry config, telemetry hook).

    Use this from your studio's BACKEND only. Never embed in a web
    bundle, mobile app, or Unity build — the ``server_integration``
    API key can mint currency and items.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        retry: RetryConfig | None = None,
        http_client: httpx.Client | None = None,
        generate_idempotency_key: Callable[[], str] | None = None,
        on_request: Callable[[RequestInfo], None] | None = None,
    ) -> None:
        self.client = KratyAdminClient(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            retry=retry,
            http_client=http_client,
            generate_idempotency_key=generate_idempotency_key,
            on_request=on_request,
        )
        self.grants = GrantsClient(self.client)
        self.inventory = InventoryClient(self.client)
        self.wallet = WalletClient(self.client)
        self.lobbies = LobbiesClient(self.client)
        self.players = PlayersClient(self.client)
        self.health = HealthClient(self.client)
        self.migrate = MigrateClient(self.client)

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self.client.close()

    def __enter__(self) -> KratyServer:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
