"""HTTP client for the Kraty ``/server/v1`` surface.

Bearer auth with a ``server_integration`` API key, auto-stamped
idempotency keys on POST/PUT/PATCH (preserved across retries),
exponential backoff + jitter on retryable statuses.
"""

from __future__ import annotations

import json
import logging
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from kraty_server_sdk.errors import KratyNetworkError, KratyServerError

logger = logging.getLogger("kraty_server_sdk")

DEFAULT_BASE_URL = "https://api.kraty.app"
RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
IDEMPOTENT_METHODS = frozenset({"POST", "PUT", "PATCH"})
_HTTP_NO_CONTENT = 204

# SDK name + version, sent as ``X-Kraty-SDK: <name>/<version>`` on
# every request. Lets the backend tell which SDK + version sent a
# given request, useful for debugging stale-SDK deployments and
# for graceful deprecation handling. Bump in lockstep with
# pyproject.toml ``version``.
_SDK_NAME = "kraty-server-sdk"
_SDK_VERSION = "0.6.0"
_SDK_USER_AGENT = f"{_SDK_NAME}/{_SDK_VERSION}"


@dataclass
class RetryConfig:
    """Retry behaviour for transient failures.

    Attributes:
        attempts: Total HTTP calls per request (1 = no retry).
        initial_delay: Backoff base in seconds; doubles each retry up
            to ``max_delay``.
        max_delay: Cap on backoff.
        jitter: Multiplier (0–1) applied as ``1 + (random()*2-1)*jitter``
            so multiple admin clients backing off don't thunder.
    """

    attempts: int = 4
    initial_delay: float = 0.2
    max_delay: float = 10.0
    jitter: float = 0.2


@dataclass
class RequestInfo:
    """Argument passed to ``on_request`` callbacks. One per HTTP
    attempt (including retries)."""

    method: str
    url: str
    attempt: int
    idempotency_key: str | None
    duration_ms: float | None = None
    status: int | None = None
    ok: bool = False


@dataclass
class _ClientOptions:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    timeout: float = 15.0
    retry: RetryConfig = field(default_factory=RetryConfig)
    http_client: httpx.Client | None = None
    generate_idempotency_key: Callable[[], str] | None = None
    on_request: Callable[[RequestInfo], None] | None = None


class KratyAdminClient:
    """Low-level HTTP client. Resource clients compose over this.

    Construct via the :class:`KratyServer` facade in most cases.
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
        if not api_key:
            raise ValueError("KratyAdminClient: api_key is required")
        self._opts = _ClientOptions(
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            retry=retry or RetryConfig(),
            http_client=http_client,
            generate_idempotency_key=generate_idempotency_key,
            on_request=on_request,
        )
        self._owns_client = http_client is None
        self._http: httpx.Client = http_client or httpx.Client(
            timeout=timeout,
            headers={
                "authorization": f"Bearer {api_key}",
                "accept": "application/json",
                "x-kraty-sdk": _SDK_USER_AGENT,
            },
        )

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> KratyAdminClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ─── core request ──────────────────────────────────────────────

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
    ) -> Any:
        """Fire a JSON request against ``/server/v1``.

        Resource clients call this. Returns the parsed JSON response
        (typically ``{"data": ...}`` for resource endpoints; callers
        unwrap as needed). Raises :class:`KratyServerError` for
        non-2xx and :class:`KratyNetworkError` for transport failures.
        """
        upper = method.upper()
        url = f"{self._opts.base_url}{path if path.startswith('/') else '/' + path}"
        idem_key = self._resolve_idempotency_key(upper, body)
        request_body = self._attach_idempotency_key(body, idem_key)

        last_err: Exception | None = None
        attempts = self._opts.retry.attempts
        for attempt in range(1, attempts + 1):
            start = time.monotonic()
            try:
                response = self._fire_once(upper, url, request_body)
                duration_ms = (time.monotonic() - start) * 1000.0
                self._fire_telemetry(
                    method=upper,
                    url=url,
                    attempt=attempt,
                    idempotency_key=idem_key,
                    duration_ms=duration_ms,
                    status=response.status_code,
                    ok=response.is_success,
                )
                if response.is_success:
                    return self._parse_body(response)
                api_err = self._as_api_error(response)
                if response.status_code in RETRYABLE_STATUSES and attempt < attempts:
                    self._sleep_backoff(attempt, response)
                    last_err = api_err
                    continue
                raise api_err
            except KratyServerError:
                raise
            except (httpx.TransportError, httpx.HTTPError) as exc:
                duration_ms = (time.monotonic() - start) * 1000.0
                self._fire_telemetry(
                    method=upper,
                    url=url,
                    attempt=attempt,
                    idempotency_key=idem_key,
                    duration_ms=duration_ms,
                    status=None,
                    ok=False,
                )
                wrapped = KratyNetworkError(str(exc), original_cause=exc)
                if attempt < attempts:
                    self._sleep_backoff(attempt)
                    last_err = wrapped
                    continue
                raise wrapped from exc
        # Unreachable in practice; the loop always returns or raises.
        raise last_err or KratyNetworkError("exhausted retries")

    # ─── internals ─────────────────────────────────────────────────

    def _fire_once(self, method: str, url: str, body: Any | None) -> httpx.Response:
        headers: dict[str, str] = {}
        content: bytes | None = None
        if body is not None:
            content = json.dumps(body).encode("utf-8")
            headers["content-type"] = "application/json"
        return self._http.request(method, url, content=content, headers=headers)

    def _resolve_idempotency_key(self, method: str, body: Any | None) -> str | None:
        if method not in IDEMPOTENT_METHODS:
            return None
        if isinstance(body, dict):
            existing = body.get("idempotencyKey")
            if isinstance(existing, str) and existing:
                return existing
        gen = self._opts.generate_idempotency_key or _default_idempotency_key
        return gen()

    def _attach_idempotency_key(self, body: Any | None, key: str | None) -> Any | None:
        if key is None:
            return body
        if body is None:
            return {"idempotencyKey": key}
        if not isinstance(body, dict):
            return body
        if "idempotencyKey" in body:
            return body
        return {**body, "idempotencyKey": key}

    def _sleep_backoff(self, attempt: int, response: httpx.Response | None = None) -> None:
        if response is not None:
            retry_after = response.headers.get("retry-after")
            if retry_after:
                try:
                    seconds = float(retry_after)
                    if seconds >= 0:
                        time.sleep(min(seconds, self._opts.retry.max_delay))
                        return
                except ValueError:
                    pass
        base = min(
            self._opts.retry.initial_delay * (2 ** (attempt - 1)),
            self._opts.retry.max_delay,
        )
        jittered = base * (1 + (random.random() * 2 - 1) * self._opts.retry.jitter)
        time.sleep(max(0.0, jittered))

    @staticmethod
    def _parse_body(response: httpx.Response) -> Any:
        if response.status_code == _HTTP_NO_CONTENT or not response.content:
            return None
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise KratyServerError(
                response.status_code,
                "internal_error",
                f"response body was not valid JSON: {response.text[:200]}",
            ) from exc

    @staticmethod
    def _as_api_error(response: httpx.Response) -> KratyServerError:
        text = response.text or ""
        payload: dict[str, Any] | None = None
        try:
            payload = json.loads(text) if text else None
        except json.JSONDecodeError:
            payload = None
        env = (payload or {}).get("error") if isinstance(payload, dict) else None
        if isinstance(env, dict) and "code" in env:
            return KratyServerError(
                response.status_code,
                str(env.get("code", "internal_error")),
                str(env.get("message", "")),
                env.get("details"),
            )
        return KratyServerError(
            response.status_code,
            "internal_error",
            f"non-2xx response without an error envelope (status={response.status_code})",
        )

    def _fire_telemetry(
        self,
        *,
        method: str,
        url: str,
        attempt: int,
        idempotency_key: str | None,
        duration_ms: float | None,
        status: int | None,
        ok: bool,
    ) -> None:
        cb = self._opts.on_request
        if cb is None:
            return
        try:
            cb(
                RequestInfo(
                    method=method,
                    url=url,
                    attempt=attempt,
                    idempotency_key=idempotency_key,
                    duration_ms=duration_ms,
                    status=status,
                    ok=ok,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("kraty_server_sdk on_request telemetry hook raised")


def _default_idempotency_key() -> str:
    return str(uuid.uuid4())
