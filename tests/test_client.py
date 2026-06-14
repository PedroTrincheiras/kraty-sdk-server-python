"""Request-layer tests: bearer auth, idempotency stamping, retry,
typed error envelopes, network failure wrapping."""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import API_KEY, BASE_URL  # type: ignore[import-not-found]

from kraty_server_sdk import KratyServer, KratyNetworkError, KratyServerError, RetryConfig


def test_sends_bearer_authorization(respx_mock, make_kraty):
    route = respx_mock.get(f"{BASE_URL}/server/v1/ping").mock(
        return_value=httpx.Response(200, json={"ok": True, "apiKey": {}}),
    )
    k = make_kraty()
    k.health.ping()
    assert route.call_count == 1
    assert route.calls[0].request.headers.get("authorization") == f"Bearer {API_KEY}"


def test_stamps_idempotency_key_on_post(respx_mock, make_kraty, key_gen):
    route = respx_mock.post(f"{BASE_URL}/server/v1/players/p/grants").mock(
        return_value=httpx.Response(201, json={"data": {"id": "g1"}}),
    )
    k = make_kraty()
    k.grants.create(
        "p",
        idempotency_key="apple_receipt_abc",
        entries=[{"type": "currency", "currencyKey": "gold", "amount": 1}],
    )
    body = json.loads(route.calls[0].request.content)
    # Caller-supplied key wins — the auto-generator must NOT fire.
    assert body["idempotencyKey"] == "apple_receipt_abc"
    assert key_gen.count == 0


def test_auto_stamps_idempotency_key_when_omitted(respx_mock, make_kraty, key_gen):
    route = respx_mock.post(f"{BASE_URL}/server/v1/players/p/inventory/sword/grant").mock(
        return_value=httpx.Response(
            200, json={"data": {"itemKey": "sword", "quantity": 1, "applied": True}}
        ),
    )
    k = make_kraty()
    k.inventory.grant("p", "sword", quantity=1)
    body = json.loads(route.calls[0].request.content)
    assert body["idempotencyKey"] == "idem-1"
    assert key_gen.count == 1


def test_does_not_stamp_idempotency_key_on_get(respx_mock, make_kraty, key_gen):
    respx_mock.get(f"{BASE_URL}/server/v1/players/p").mock(
        return_value=httpx.Response(200, json={"data": {"player": {}}}),
    )
    k = make_kraty()
    k.players.get("p")
    assert key_gen.count == 0


def test_throws_kraty_server_error_on_non_2xx(respx_mock, make_kraty):
    respx_mock.get(f"{BASE_URL}/server/v1/players/missing").mock(
        return_value=httpx.Response(
            404, json={"error": {"code": "not_found", "message": "no player"}}
        ),
    )
    k = make_kraty()
    with pytest.raises(KratyServerError) as exc_info:
        k.players.get("missing")
    err = exc_info.value
    assert err.status == 404
    assert err.code == "not_found"
    assert err.is_not_found is True
    assert err.is_idempotency_conflict is False


def test_retries_on_503_then_succeeds(respx_mock, make_kraty):
    route = respx_mock.get(f"{BASE_URL}/server/v1/ping").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(200, json={"ok": True, "apiKey": {}}),
        ],
    )
    k = make_kraty()
    k.health.ping()
    assert route.call_count == 2


def test_preserves_idempotency_key_across_retries(respx_mock, make_kraty, key_gen):
    route = respx_mock.post(f"{BASE_URL}/server/v1/players/p/inventory/sword/grant").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, json={"data": {"itemKey": "sword", "quantity": 1, "applied": True}}),
        ],
    )
    k = make_kraty()
    k.inventory.grant("p", "sword", quantity=1)
    assert route.call_count == 3
    keys = [json.loads(c.request.content)["idempotencyKey"] for c in route.calls]
    assert keys == ["idem-1", "idem-1", "idem-1"]
    # Auto-gen fires once for the whole request, not per retry.
    assert key_gen.count == 1


def test_gives_up_after_retry_budget_and_raises(respx_mock, make_kraty):
    route = respx_mock.get(f"{BASE_URL}/server/v1/ping").mock(
        side_effect=[httpx.Response(503)] * 3,
    )
    k = make_kraty()
    with pytest.raises(KratyServerError):
        k.health.ping()
    assert route.call_count == 3


def test_honors_retry_after_on_429(respx_mock, make_kraty):
    route = respx_mock.get(f"{BASE_URL}/server/v1/ping").mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(200, json={"ok": True, "apiKey": {}}),
        ],
    )
    k = make_kraty()
    k.health.ping()
    assert route.call_count == 2


def test_does_not_retry_on_4xx_other_than_408_425_429(respx_mock, make_kraty):
    route = respx_mock.post(
        f"{BASE_URL}/server/v1/players/p/grants"
    ).mock(
        return_value=httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "no game"}},
        ),
    )
    k = make_kraty()
    with pytest.raises(KratyServerError):
        k.grants.create(
            "p",
            idempotency_key="x",
            entries=[{"type": "currency", "currencyKey": "gold", "amount": 1}],
        )
    # No retry — 404 is terminal.
    assert route.call_count == 1


def test_wraps_network_crash_as_kraty_network_error(respx_mock, make_kraty):
    respx_mock.get(f"{BASE_URL}/server/v1/ping").mock(
        side_effect=httpx.ConnectError("ECONNRESET"),
    )
    k = make_kraty(retry=RetryConfig(attempts=2, initial_delay=0.001, max_delay=0.002, jitter=0))
    with pytest.raises(KratyNetworkError) as exc_info:
        k.health.ping()
    assert isinstance(exc_info.value.original_cause, httpx.ConnectError)


def test_on_request_telemetry_fires(respx_mock, key_gen):
    respx_mock.get(f"{BASE_URL}/server/v1/ping").mock(
        return_value=httpx.Response(200, json={"ok": True, "apiKey": {}}),
    )
    events = []
    k = KratyServer(
        api_key=API_KEY,
        base_url=BASE_URL,
        retry=RetryConfig(attempts=2, initial_delay=0.001, max_delay=0.002, jitter=0),
        generate_idempotency_key=key_gen,
        on_request=lambda info: events.append({"status": info.status, "ok": info.ok}),
    )
    try:
        k.health.ping()
    finally:
        k.close()
    assert events == [{"status": 200, "ok": True}]
