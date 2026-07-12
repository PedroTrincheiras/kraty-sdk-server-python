"""Resource clients for the Kraty server SDK.

Each class corresponds to one slice of the ``/server/v1`` surface
and accepts pre-validated kwargs that get JSON-serialised onto the
wire. Keys in the request body are camelCase (matching the API
contract); the Python parameters are snake_case for ergonomics, and
the methods translate.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from kraty_server_sdk.client import KratyAdminClient


class GrantsClient:
    """``/server/v1/players/:externalId/grants``: manual grant minting.

    Used for IAP fulfilment, make-goods, manual operator rewards, and
    any other server-issued payout.
    """

    def __init__(self, client: KratyAdminClient) -> None:
        self._client = client

    def create(
        self,
        external_player_id: str,
        *,
        idempotency_key: str,
        entries: list[dict[str, Any]],
        kind: str = "reward",
        expires_at: str | None = None,
        source_kind: str = "api",
        source_ref_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST ``/server/v1/players/:externalId/grants``: mint a new grant.

        Args:
            external_player_id: Stable player identifier.
            idempotency_key: Required, usually the IAP receipt id.
                Replays with the same body return the original grant;
                replays with a DIFFERENT body return 409
                ``idempotency_conflict``.
            entries: At least one. Each entry is one of:

                * ``{"type": "currency", "currencyKey": str, "amount": int}``
                * ``{"type": "item",     "itemKey": str, "quantity": int, "parameters"?: dict}``
                * ``{"type": "crate",    "crateItemKey": str, "quantity": int}``
            kind: ``"reward"`` (default) or ``"crate"``. Crates need to
                be ``/open``\\ ed by the player to roll their contents.
            expires_at: Optional ISO datetime; the grant becomes
                unclaimable after this.
            source_kind: ``"api"`` (default) or ``"admin"``.
            source_ref_id: Tracing id (usually the IAP receipt).
            metadata: Free-form blob persisted on the grant row.

        Returns: The grant row (camelCase dict matching the wire shape).
        """
        body: dict[str, Any] = {
            "idempotencyKey": idempotency_key,
            "kind": kind,
            "entries": entries,
            "sourceKind": source_kind,
        }
        if expires_at is not None:
            body["expiresAt"] = expires_at
        if source_ref_id is not None:
            body["sourceRefId"] = source_ref_id
        if metadata is not None:
            body["metadata"] = metadata
        env = self._client.request(
            "POST",
            f"/server/v1/players/{_enc(external_player_id)}/grants",
            body=body,
        )
        return _data(env)

    def ack(
        self,
        external_player_id: str,
        grant_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """POST ``/server/v1/players/:externalId/grants/:grantId/ack``: server-side claim.

        Use this when your backend wants to flip a grant to ``claimed``
        without the player's client SDK having to round-trip (e.g.
        consumable that's already applied server-side). Records
        ``ackedBy='server_api'`` on the audit row. Idempotent on
        ``grantId``.
        """
        body: dict[str, Any] = {}
        if idempotency_key is not None:
            body["idempotencyKey"] = idempotency_key
        env = self._client.request(
            "POST",
            f"/server/v1/players/{_enc(external_player_id)}/grants/{_enc(grant_id)}/ack",
            body=body,
        )
        return _data(env)


class InventoryClient:
    """``/server/v1/players/:p/inventory(/...)``: platform-managed inventory grant + revoke.

    Only meaningful when the game has
    ``settings.inventoryManagement === 'platform'``. For studio-managed
    games these calls are inert.
    """

    def __init__(self, client: KratyAdminClient) -> None:
        self._client = client

    def grant(
        self,
        external_player_id: str,
        item_key: str,
        *,
        quantity: int,
        reason: str | None = None,
        source_ref_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """POST ``/server/v1/players/:p/inventory/:itemKey/grant``: atomic increment.

        Used for IAP item delivery, make-goods, or operator-issued
        items. Supply the IAP receipt id as ``idempotency_key`` so
        retries don't double-grant.
        """
        body = self._adjust_body(quantity, reason, source_ref_id, idempotency_key)
        env = self._client.request(
            "POST",
            f"/server/v1/players/{_enc(external_player_id)}/inventory/{_enc(item_key)}/grant",
            body=body,
        )
        return _data(env)

    def revoke(
        self,
        external_player_id: str,
        item_key: str,
        *,
        quantity: int,
        reason: str | None = None,
        source_ref_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """POST ``/server/v1/players/:p/inventory/:itemKey/revoke``: atomic decrement.

        Used for chargebacks and admin corrections. 409 on insufficient
        quantity, because the audit ledger never goes negative.
        """
        body = self._adjust_body(quantity, reason, source_ref_id, idempotency_key)
        env = self._client.request(
            "POST",
            f"/server/v1/players/{_enc(external_player_id)}/inventory/{_enc(item_key)}/revoke",
            body=body,
        )
        return _data(env)

    @staticmethod
    def _adjust_body(
        quantity: int,
        reason: str | None,
        source_ref_id: str | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"quantity": quantity}
        if reason is not None:
            body["reason"] = reason
        if source_ref_id is not None:
            body["sourceRefId"] = source_ref_id
        if idempotency_key is not None:
            body["idempotencyKey"] = idempotency_key
        return body


class WalletClient:
    """``/server/v1/players/:p/wallet(/...)``: server-side currency mint + burn.

    Counterpart to the client SDK's ``wallet.debit``: only the server
    surface can credit balance, which is why this server SDK is a
    separate package.
    """

    def __init__(self, client: KratyAdminClient) -> None:
        self._client = client

    def credit(
        self,
        external_player_id: str,
        economy_key: str,
        *,
        amount: int,
        reason: str | None = None,
        source_ref_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """POST ``/server/v1/players/:p/wallet/:economyKey/credit``: atomic increment.

        Used for IAP currency fulfilment, support reissues, and prize
        distribution. Pass the receipt id as ``idempotency_key``.
        """
        body = self._adjust_body(amount, reason, source_ref_id, idempotency_key)
        env = self._client.request(
            "POST",
            f"/server/v1/players/{_enc(external_player_id)}/wallet/{_enc(economy_key)}/credit",
            body=body,
        )
        return _data(env)

    def debit(
        self,
        external_player_id: str,
        economy_key: str,
        *,
        amount: int,
        reason: str | None = None,
        source_ref_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """POST ``/server/v1/players/:p/wallet/:economyKey/debit``: atomic decrement.

        Used for refunds and admin corrections. 409 on insufficient
        balance.
        """
        body = self._adjust_body(amount, reason, source_ref_id, idempotency_key)
        env = self._client.request(
            "POST",
            f"/server/v1/players/{_enc(external_player_id)}/wallet/{_enc(economy_key)}/debit",
            body=body,
        )
        return _data(env)

    @staticmethod
    def _adjust_body(
        amount: int,
        reason: str | None,
        source_ref_id: str | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"amount": amount}
        if reason is not None:
            body["reason"] = reason
        if source_ref_id is not None:
            body["sourceRefId"] = source_ref_id
        if idempotency_key is not None:
            body["idempotencyKey"] = idempotency_key
        return body


class LobbiesClient:
    """``/server/v1/games/:gameId/.../lobbies``: push pre-matched lobbies.

    Use when your studio's own matchmaker (Steam, GameLift, Photon)
    already chose a roster and you want Kraty to host the event
    window + scoring.
    """

    def __init__(self, client: KratyAdminClient) -> None:
        self._client = client

    def push(
        self,
        game_id: str,
        event_key: str,
        *,
        key: str,
        external_player_ids: list[str],
        capacity: int | None = None,
        fill_bots: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST ``/server/v1/games/:gameId/events/:eventKey/lobbies``: create a pre-matched lobby.

        Idempotent on ``key`` (your studio's lobby id). Requires the
        event's ``leaderboardMode`` to be ``'lobby_matched'``.
        """
        body: dict[str, Any] = {
            "key": key,
            "externalPlayerIds": external_player_ids,
        }
        if capacity is not None:
            body["capacity"] = capacity
        if fill_bots is not None:
            body["fillBots"] = fill_bots
        if metadata is not None:
            body["metadata"] = metadata
        env = self._client.request(
            "POST",
            f"/server/v1/games/{_enc(game_id)}/events/{_enc(event_key)}/lobbies",
            body=body,
        )
        return _data(env)

    def read(self, game_id: str, lobby_id: str) -> dict[str, Any]:
        """GET ``/server/v1/games/:gameId/lobbies/:lobbyId``: server-side lobby read."""
        env = self._client.request(
            "GET",
            f"/server/v1/games/{_enc(game_id)}/lobbies/{_enc(lobby_id)}",
        )
        return _data(env)


class LeaderboardsClient:
    """``/server/v1/leaderboards/:key/score``: server-authoritative scoring.

    Unlike the client SDK's score path, this surface is NOT subject to
    the game's ``acceptClientScores`` gate: the ``server_integration``
    key is trusted, so studios that keep scoring server-side (anti-cheat,
    simulation results) write here.
    """

    def __init__(self, client: KratyAdminClient) -> None:
        self._client = client

    def submit_score(
        self,
        external_player_id: str,
        key: str,
        value: float,
        *,
        segment: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """POST ``/server/v1/leaderboards/:key/score``: submit a score
        for a player on a score-ranked board.

        Segmentation: on ``context`` boards pass ``segment`` as the
        bucket value; on ``progression`` boards omit it (the server
        derives the bucket from the player's progression state); on
        unsegmented boards it's ignored.

        Returns ``{"leaderboardId": str, "score": number, "rank": int | None}``.

        Raises ``KratyServerError`` with ``code='not_found'`` for an
        unknown player or board, and ``code='score_not_supported'`` (400)
        for progression-ranked boards (which don't accept raw scores;
        adjust the progression item instead).
        """
        body: dict[str, Any] = {
            "externalPlayerId": external_player_id,
            "value": value,
        }
        if segment is not None:
            body["segment"] = segment
        if idempotency_key is not None:
            body["idempotencyKey"] = idempotency_key
        env = self._client.request(
            "POST",
            f"/server/v1/leaderboards/{_enc(key)}/score",
            body=body,
        )
        return _data(env)


class EventsClient:
    """``/server/v1/players/:externalId/events/...``: server-authoritative
    event progress.

    Same shape as the client SDK's progress endpoint, but driven from
    your backend (trusted simulation, server-side match results) rather
    than the game client.
    """

    def __init__(self, client: KratyAdminClient) -> None:
        self._client = client

    def report_progress(
        self,
        external_player_id: str,
        event_key: str,
        attempt_id: str,
        *,
        mode: str,
        metric_value: float | None = None,
        metrics: dict[str, float] | None = None,
        occurred_at: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """POST
        ``/server/v1/players/:externalId/events/:eventKey/attempts/:attemptId/progress``:
        push a metric update onto an in-flight attempt.

        ``mode`` is ``"set"`` (write the value as the new metric) or
        ``"increment"`` (add to the current). Returns
        ``{"attempt": {...}, "milestonesFired": [...]}``: the updated
        attempt plus any milestones that fired (and the grants they
        wrote) this call.
        """
        body: dict[str, Any] = {"mode": mode}
        if metric_value is not None:
            body["metricValue"] = metric_value
        if metrics is not None:
            body["metrics"] = metrics
        if occurred_at is not None:
            body["occurredAt"] = occurred_at
        if idempotency_key is not None:
            body["idempotencyKey"] = idempotency_key
        env = self._client.request(
            "POST",
            f"/server/v1/players/{_enc(external_player_id)}"
            f"/events/{_enc(event_key)}/attempts/{_enc(attempt_id)}/progress",
            body=body,
        )
        return _data(env)

    # Alias matching the client SDK's ``progress`` verb, so the same name
    # works when moving score submission to your server. ``report_progress``
    # stays the canonical server-SDK name.
    progress = report_progress

    def finish(
        self,
        external_player_id: str,
        event_key: str,
        attempt_id: str,
    ) -> dict[str, Any]:
        """POST
        ``/server/v1/players/:externalId/events/:eventKey/attempts/:attemptId/finish``:
        end an in-progress attempt now, finalizing with its current score
        (server-authoritative counterpart to the client SDK ``finish``).
        Returns ``{"attempt": {...}, "outcome": "completed" | "expired"}``:
        ``completed`` for a score-attack end / target met, ``expired`` for a
        target event ended early.
        """
        env = self._client.request(
            "POST",
            f"/server/v1/players/{_enc(external_player_id)}"
            f"/events/{_enc(event_key)}/attempts/{_enc(attempt_id)}/finish",
        )
        return _data(env)


class PlayersClient:
    """``/server/v1/players/:externalId``: unified player snapshot,
    plus GDPR delete + export."""

    def __init__(self, client: KratyAdminClient) -> None:
        self._client = client

    def get(self, external_player_id: str) -> dict[str, Any]:
        """GET ``/server/v1/players/:externalId``: returns ``{player, inventory, wallet, recentGrants}``."""
        env = self._client.request(
            "GET",
            f"/server/v1/players/{_enc(external_player_id)}",
        )
        return _data(env)

    def delete(
        self,
        external_player_id: str,
        *,
        reason: str = "gdpr_erasure",
    ) -> dict[str, Any]:
        """POST ``/server/v1/players/:externalId/delete``: GDPR
        Article 17 right of erasure.

        Anonymizes the player row in place and cascades through
        attempts, lobbies, and the Redis leaderboard meta. The
        financial ledger (grants, item / wallet ledgers) is retained
        per audit requirements; its ``playerId`` FK now points at an
        anonymized row.

        Returns the outcome::

            {
              "playerId": "<uuid|null>",
              "externalPlayerId": "<original>",
              "anonymizedExternalId": "__deleted_<uuid>__ | null",
              "deletedAt": "<iso>",
              "attemptsAnonymized": int,
              "lobbiesAnonymized": int,
              "leaderboardsScrubbed": int,
              "status": "erased" | "no_op_already_erased" | "no_op_never_existed"
            }

        ``reason`` is one of ``gdpr_erasure`` (default), ``studio_request``,
        ``test``. Recorded on the audit log.

        Emits one final ``player.deleted`` webhook with the original
        external id so your backend can mirror the deletion. Idempotent:
        erasure for a never-existed player succeeds with
        ``status: "no_op_never_existed"`` (GDPR semantics: nothing to erase).
        """
        env = self._client.request(
            "POST",
            f"/server/v1/players/{_enc(external_player_id)}/delete",
            body={"reason": reason},
        )
        return _data(env)

    def export(self, external_player_id: str) -> dict[str, Any]:
        """GET ``/server/v1/players/:externalId/export``: GDPR
        Article 15 right of access.

        Returns the full machine-readable bundle of everything Kraty
        stores about the player (profile, attempts, grants, inventory,
        wallet, lobbies). Each list is hard-capped at 1,000 rows.

        Raises ``KratyServerError`` with ``code='not_found'`` when the
        player is unknown to Kraty.
        """
        env = self._client.request(
            "GET",
            f"/server/v1/players/{_enc(external_player_id)}/export",
        )
        return _data(env)

    def ban(self, external_player_id: str, *, reason: str) -> dict[str, Any]:
        """POST ``/server/v1/players/:externalId/ban``: soft-ban a
        player. Gates future SDK writes (events.start / progress /
        claim / open / debit / consume / register all return 403
        ``player_banned``) without touching existing scores or grants.

        Typical use case: studio's own anti-cheat pipeline detects an
        anomaly and bans the player automatically. The actor is
        recorded as ``api_key:<prefix>`` on the audit row.

        Idempotent: re-banning refreshes the reason but doesn't
        re-fire the webhook.
        """
        env = self._client.request(
            "POST",
            f"/server/v1/players/{_enc(external_player_id)}/ban",
            body={"reason": reason},
        )
        return _data(env)

    def unban(self, external_player_id: str) -> dict[str, Any]:
        """POST ``/server/v1/players/:externalId/unban``: lift a
        soft-ban. Symmetric to :meth:`ban`. Idempotent: unbanning a
        non-banned player returns ``applied: False``.
        """
        env = self._client.request(
            "POST",
            f"/server/v1/players/{_enc(external_player_id)}/unban",
        )
        return _data(env)

    def merge(
        self,
        from_external_player_id: str,
        to_external_player_id: str,
    ) -> dict[str, Any]:
        """POST ``/server/v1/players/:from/merge-into/:to``: fold the
        source player's record into the target.

        Reassigns attempts, grants, item + wallet ledgers; sums
        balances on key collision; dedupes lobby memberships; rewrites
        the source row to a ``__merged_<uuid>__`` placeholder so the
        original external id is available for re-registration.

        Typical use: guest player on a fresh device finishes
        onboarding, signs in via OAuth, and the studio backend folds
        the guest record into the authenticated player.

        Idempotent: replaying after the merge returns
        ``status='no_op_already_merged'`` with the existing target.

        Raises ``KratyServerError`` with ``code='not_found'`` on
        missing players, or ``code='conflict'`` (422) on invalid
        merges (same player, target banned/deleted).
        """
        env = self._client.request(
            "POST",
            f"/server/v1/players/{_enc(from_external_player_id)}"
            f"/merge-into/{_enc(to_external_player_id)}",
        )
        return _data(env)


class HealthClient:
    """``/server/v1/ping``: connectivity + key-info echo."""

    def __init__(self, client: KratyAdminClient) -> None:
        self._client = client

    def ping(self) -> dict[str, Any]:
        """Useful for deploy-time smoke tests: confirms the env var is wired to the right key."""
        result = self._client.request("GET", "/server/v1/ping")
        return result if isinstance(result, dict) else {}


class MigrateClient:
    """``/server/v1/migrate/*``: bulk-import endpoints for studios moving
    existing players, wallets, and inventory into Kraty from another
    platform.

    Each method accepts up to 1,000 rows per call. Every row carries
    its own ``idempotency_key`` (typically the studio's stable id for
    that player / wallet entry / inventory holding) so retries are
    safe at the row level. Bad rows are captured in the response's
    ``failures`` list; the rest of the batch still applies.

    Studios with larger datasets loop client-side::

        for chunk in chunked(all_players, 1000):
            out = kraty.migrate.players(chunk)
            if out["failed"] > 0:
                collect_for_retry(out["failures"])

    Webhooks are NOT emitted during migration, because a 100k-player
    import would otherwise flood the studio's own backend.
    """

    def __init__(self, client: KratyAdminClient) -> None:
        self._client = client

    def players(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """POST ``/server/v1/migrate/players``: bulk-import players.

        Each row shape::

            {
                "externalPlayerId": str,
                "contextSnapshot": dict | None,
                "idempotencyKey": str,
            }

        Returns the migration outcome: ``{applied, skipped, failed, failures}``.
        """
        env = self._client.request("POST", "/server/v1/migrate/players", body={"rows": rows})
        return _data(env)

    def wallet(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """POST ``/server/v1/migrate/wallet``: bulk-credit wallet balances.

        Each row shape::

            {
                "externalPlayerId": str,
                "economyKey": str,
                "amount": int,            # positive only
                "reason": str | None,
                "idempotencyKey": str,
            }
        """
        env = self._client.request("POST", "/server/v1/migrate/wallet", body={"rows": rows})
        return _data(env)

    def inventory(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """POST ``/server/v1/migrate/inventory``: bulk-grant inventory rows.

        Each row shape::

            {
                "externalPlayerId": str,
                "itemKey": str,
                "quantity": int,
                "parameters": dict | None,
                "reason": str | None,
                "idempotencyKey": str,
            }
        """
        env = self._client.request("POST", "/server/v1/migrate/inventory", body={"rows": rows})
        return _data(env)


# ─── helpers ────────────────────────────────────────────────────────


def _enc(s: str) -> str:
    """Percent-encode a path segment."""
    return urllib.parse.quote(s, safe="")


def _data(env: Any) -> dict[str, Any]:
    """Unwrap the ``{"data": ...}`` envelope every resource endpoint returns."""
    if not isinstance(env, dict):
        return {}
    env_dict: dict[str, Any] = env
    data = env_dict.get("data")
    if isinstance(data, dict):
        data_dict: dict[str, Any] = data
        return data_dict
    # Defensive fallback: if the server ever drops the envelope, hand
    # back whatever's there so callers can still inspect it.
    return env_dict
