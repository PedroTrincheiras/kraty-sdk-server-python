"""Tests for verify_webhook.

The verifier MUST byte-for-byte match the Node server SDK's
``verifyWebhook`` AND the backend's
``apps/backend/src/core/webhooks/signing.ts``. The fixture signatures
below are computed the same way the backend computes them, so any
divergence in the verifier surfaces as a failing test.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac

from kraty_server_sdk import verify_webhook

SECRET = "whsec_test_12345"
BODY = '{"kind":"grant.created","grant":{"id":"g_1"}}'
NOW = _dt.datetime(2026, 6, 8, 12, 0, 0, tzinfo=_dt.timezone.utc)
NOW_SECONDS = int(NOW.timestamp())


def _sign(secret: str, body: str, t_seconds: int) -> str:
    mac = hmac.new(
        secret.encode("utf-8"),
        f"{t_seconds}.{body}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"t={t_seconds},v1={mac}"


def test_accepts_fresh_valid_signature():
    header = _sign(SECRET, BODY, NOW_SECONDS)
    assert verify_webhook(
        raw_body=BODY, signature_header=header, secret=SECRET, now=NOW
    )


def test_accepts_bytes_body():
    header = _sign(SECRET, BODY, NOW_SECONDS)
    assert verify_webhook(
        raw_body=BODY.encode("utf-8"),
        signature_header=header,
        secret=SECRET,
        now=NOW,
    )


def test_rejects_signature_older_than_default_window():
    header = _sign(SECRET, BODY, NOW_SECONDS - 301)
    assert not verify_webhook(
        raw_body=BODY, signature_header=header, secret=SECRET, now=NOW
    )


def test_honors_custom_tolerance():
    header = _sign(SECRET, BODY, NOW_SECONDS - 600)
    assert verify_webhook(
        raw_body=BODY,
        signature_header=header,
        secret=SECRET,
        tolerance_seconds=900,
        now=NOW,
    )


def test_rejects_signature_more_than_60s_in_future():
    header = _sign(SECRET, BODY, NOW_SECONDS + 120)
    assert not verify_webhook(
        raw_body=BODY, signature_header=header, secret=SECRET, now=NOW
    )


def test_rejects_tampered_body():
    header = _sign(SECRET, BODY, NOW_SECONDS)
    tampered = BODY.replace("g_1", "g_2")
    assert not verify_webhook(
        raw_body=tampered, signature_header=header, secret=SECRET, now=NOW
    )


def test_rejects_wrong_secret():
    header = _sign(SECRET, BODY, NOW_SECONDS)
    assert not verify_webhook(
        raw_body=BODY, signature_header=header, secret="whsec_wrong", now=NOW
    )


def test_rejects_missing_v1_field():
    header = f"t={NOW_SECONDS}"
    assert not verify_webhook(
        raw_body=BODY, signature_header=header, secret=SECRET, now=NOW
    )


def test_rejects_missing_t_field():
    mac = hmac.new(
        SECRET.encode("utf-8"),
        f"{NOW_SECONDS}.{BODY}".encode(),
        hashlib.sha256,
    ).hexdigest()
    header = f"v1={mac}"
    assert not verify_webhook(
        raw_body=BODY, signature_header=header, secret=SECRET, now=NOW
    )


def test_rejects_non_numeric_t():
    mac = hmac.new(
        SECRET.encode("utf-8"),
        f"{NOW_SECONDS}.{BODY}".encode(),
        hashlib.sha256,
    ).hexdigest()
    header = f"t=not-a-number,v1={mac}"
    assert not verify_webhook(
        raw_body=BODY, signature_header=header, secret=SECRET, now=NOW
    )


def test_rejects_malformed_v1_hex():
    header = f"t={NOW_SECONDS},v1=not-hex"
    assert not verify_webhook(
        raw_body=BODY, signature_header=header, secret=SECRET, now=NOW
    )


def test_rejects_empty_header():
    assert not verify_webhook(
        raw_body=BODY, signature_header="", secret=SECRET, now=NOW
    )


def test_tolerates_whitespace_around_fields():
    mac = hmac.new(
        SECRET.encode("utf-8"),
        f"{NOW_SECONDS}.{BODY}".encode(),
        hashlib.sha256,
    ).hexdigest()
    header = f" t={NOW_SECONDS} , v1={mac} "
    assert verify_webhook(
        raw_body=BODY, signature_header=header, secret=SECRET, now=NOW
    )
