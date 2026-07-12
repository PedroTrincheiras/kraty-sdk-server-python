"""Error types for the Kraty server SDK.

Mirrors the sealed-ish error codes the backend's ``/server/v1``
surface returns. Codes are stable strings; match on
``KratyServerError.code``, not on ``KratyServerError.message``.
"""

from __future__ import annotations

from typing import Any


class KratyServerError(Exception):
    """Raised for every non-2xx response from the Kraty server API.

    Attributes:
        status: HTTP status code.
        code: Sealed-set error code from the backend's
            ``{"error": {"code", "message", "details"}}`` envelope.
        message: Human-readable message (the SDK uses this as the
            ``Exception`` message too).
        details: Optional structured details, usually a dict with
            code-specific fields (e.g. ``{"resource": "gold"}``).

    Use the typed ``is_*`` properties to switch on a code; they're
    cheaper to read than a chain of string comparisons and immune to
    typos. One property exists per code; if you need to match on a
    code the SDK hasn't bumped to yet, use the generic
    :meth:`KratyServerError.is_code`.
    """

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: Any | None = None,
    ) -> None:
        super().__init__(f"[{status}] {code}: {message}")
        self.status = status
        self.code = code
        self.api_message = message
        self.details = details

    def is_code(self, code: str) -> bool:
        """Generic code matcher. Useful when matching on a code the
        SDK doesn't yet have a typed getter for (e.g. a new code the
        backend added before an SDK release).

        Example::

            if err.is_code("event_disabled"):
                skip_fulfilment()
        """
        return self.code == code

    # ── core ─────────────────────────────────────────────────────────

    @property
    def is_unauthenticated(self) -> bool:
        """401: ``Authorization`` header missing on a protected route."""
        return self.code == "unauthenticated"

    @property
    def is_session_invalid(self) -> bool:
        """401: Bearer token is malformed, revoked, or rejected."""
        return self.code == "session_invalid"

    @property
    def is_forbidden(self) -> bool:
        """403: auth was valid but permission set / studio / game didn't match the route.

        Usually a misconfigured key: the ``server_integration`` key
        in your env should match the game you're calling against.
        """
        return self.code == "forbidden"

    @property
    def is_not_found(self) -> bool:
        """404: referenced resource doesn't exist or isn't visible to this studio.

        For grant ack: the grant id was never minted. For inventory
        grant: the item key isn't in the catalog. For player lookup:
        no player with that externalId.
        """
        return self.code == "not_found"

    @property
    def is_player_banned(self) -> bool:
        """403: the player has been soft-banned by the studio.

        Banned players cannot drive SDK writes (events.start /
        progress, grants.claim, etc.) and cannot re-register a fresh
        secret. Server-side administrative writes on the account
        still work; lift the ban with ``kraty.players.unban``.
        """
        return self.code == "player_banned"

    @property
    def is_validation_failed(self) -> bool:
        """400: request body / query failed schema validation. ``details`` carries field-level errors."""
        return self.code == "validation_failed"

    @property
    def is_conflict(self) -> bool:
        """409: generic mutation conflict (e.g. wallet debit on a 0 balance, mode mismatch).

        More specific 409 codes (``idempotency_conflict``) get their
        own getters; this catches the rest.
        """
        return self.code == "conflict"

    @property
    def is_rate_limited(self) -> bool:
        """429: per-key rate limit exceeded.

        ``Retry-After`` header carries the wait. SDK auto-retries
        with backoff before surfacing, so by the time you see this,
        the retry budget is exhausted.
        """
        return self.code == "rate_limited"

    @property
    def is_internal_error(self) -> bool:
        """500: unhandled exception. Logged + alerted server-side."""
        return self.code == "internal_error"

    @property
    def is_tenant_mismatch(self) -> bool:
        """403: cross-studio access attempt (RLS rejected the row). Misconfigured key."""
        return self.code == "tenant_mismatch"

    @property
    def is_idempotency_conflict(self) -> bool:
        """409: same ``idempotency_key`` was used with a different request body within the cache TTL.

        Means a duplicate IAP fulfilment is in flight with a different
        payload, so investigate before retrying.
        """
        return self.code == "idempotency_conflict"

    # ── per-game state ───────────────────────────────────────────────

    @property
    def is_event_disabled(self) -> bool:
        """409: the event is configured but disabled. Server fulfilment paths usually shouldn't hit this."""
        return self.code == "event_disabled"

    @property
    def is_invalid_metric(self) -> bool:
        """400: a manual-grant entry referenced an unknown metric / item / currency key."""
        return self.code == "invalid_metric"


class KratyNetworkError(Exception):
    """Raised when the request never produced an HTTP response.

    DNS failure, socket reset, abort / timeout, etc. The SDK
    auto-retries network errors with backoff before surfacing this,
    so by the time you see one, the retry budget is exhausted.
    """

    def __init__(self, message: str, original_cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.original_cause = original_cause
