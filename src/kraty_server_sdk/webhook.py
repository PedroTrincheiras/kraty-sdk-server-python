"""Kraty webhook signature verification.

The platform stamps every outgoing webhook with an ``X-Signature``
header in the form ``t=<unixSeconds>,v1=<hex>``, where the v1 hex is
``HMAC_SHA256(secret, "<t>.<rawBody>")``. Receivers MUST:

1. Capture the **raw** request body (not the parsed JSON, since even a
   re-stringification can change byte ordering or whitespace, and
   that's enough to break the HMAC).
2. Read ``X-Signature`` from the request headers.
3. Look up the webhook's secret from your portal config.
4. Call :func:`verify_webhook`. Reject the request with 401 if it
   returns ``False``.

The function also rejects signatures whose timestamp is more than
``tolerance_seconds`` (default 300s) in the past, which defeats
replay attacks even if an attacker captures a real header, and
more than 60s in the future, which catches forged headers with
tampered clocks.

Constant-time compare under the hood (:func:`hmac.compare_digest`),
so signature-recovery via timing leaks isn't viable.

Example FastAPI receiver::

    from fastapi import FastAPI, Header, HTTPException, Request
    from kraty_server_sdk import verify_webhook

    app = FastAPI()

    @app.post("/kraty/webhook")
    async def kraty_webhook(
        request: Request,
        x_signature: str = Header(...),
    ):
        raw = await request.body()
        if not verify_webhook(
            raw_body=raw,
            signature_header=x_signature,
            secret=os.environ["KRATY_WEBHOOK_SECRET"],
        ):
            raise HTTPException(status_code=401, detail="bad signature")
        event = await request.json()
        # … handle the event …
        return {"ok": True}
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac

# Window for "this signature was issued in the future": we tolerate
# up to 60s of forward clock skew, anything more rejects as forged.
_MAX_FORWARD_SKEW_SECONDS = 60


def verify_webhook(
    *,
    raw_body: str | bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: int = 300,
    now: _dt.datetime | None = None,
) -> bool:
    """Returns True iff the signature header was produced by
    ``HMAC_SHA256(secret, "<t>.<raw_body>")`` within the tolerance
    window.

    Args:
        raw_body: The bytes of the request body, exactly as received
            on the wire. If you pass a ``str`` it's UTF-8 encoded;
            for any other encoding, encode manually first.
        signature_header: Verbatim value of the ``X-Signature``
            header.
        secret: The webhook's signing secret from your portal config.
        tolerance_seconds: Replay-window cap. Default 300 (5 minutes).
        now: Override for tests; defaults to
            ``datetime.now(timezone.utc)``.

    Returns:
        ``True`` on a valid signature, ``False`` on any failure
        (parse error, timestamp out of window, body tampered,
        wrong secret).
    """
    parsed = _parse_header(signature_header)
    if parsed is None:
        return False

    current = now or _dt.datetime.now(_dt.timezone.utc)
    now_seconds = int(current.timestamp())
    skew = now_seconds - parsed.t
    if skew > tolerance_seconds:
        # too old → replay
        return False
    if skew < -_MAX_FORWARD_SKEW_SECONDS:
        # > 60s in the future → forged / bad clock
        return False

    body_bytes = raw_body.encode("utf-8") if isinstance(raw_body, str) else bytes(raw_body)
    mac_input = f"{parsed.t}.".encode() + body_bytes
    expected_hex = hmac.new(
        secret.encode("utf-8"), mac_input, hashlib.sha256
    ).hexdigest()

    try:
        expected = bytes.fromhex(expected_hex)
        provided = bytes.fromhex(parsed.v1)
    except ValueError:
        return False

    if len(expected) == 0 or len(expected) != len(provided):
        return False
    return hmac.compare_digest(expected, provided)


class _Parsed:
    __slots__ = ("t", "v1")

    def __init__(self, t: int, v1: str) -> None:
        self.t = t
        self.v1 = v1


def _parse_header(header: str) -> _Parsed | None:
    if not header:
        return None
    t: int | None = None
    v1: str | None = None
    for part in header.split(","):
        kv = part.strip()
        if "=" not in kv:
            continue
        k, _, v = kv.partition("=")
        if not v:
            continue
        if k == "t":
            try:
                t = int(v)
            except ValueError:
                return None
        elif k == "v1":
            v1 = v
    if t is None or v1 is None or len(v1) == 0:
        return None
    return _Parsed(t, v1)
