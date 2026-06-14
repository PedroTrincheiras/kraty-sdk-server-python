"""Resource-client tests: URL shapes, request bodies, typed errors."""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import BASE_URL  # type: ignore[import-not-found]

from kraty_server_sdk import KratyServerError

# ─── GrantsClient ───────────────────────────────────────────────────


def test_grants_create_posts_to_right_url(respx_mock, make_kraty):
    route = respx_mock.post(f"{BASE_URL}/server/v1/players/player_42/grants").mock(
        return_value=httpx.Response(
            201,
            json={
                "data": {
                    "id": "g1",
                    "kind": "reward",
                    "contents": {},
                    "sourceKind": "api",
                    "sourceRefId": "rcpt",
                    "parentGrantId": None,
                    "status": "pending",
                    "rolledAt": None,
                    "claimedAt": None,
                    "expiresAt": None,
                    "createdAt": "2026-01-01",
                }
            },
        )
    )
    k = make_kraty()
    g = k.grants.create(
        "player_42",
        idempotency_key="apple_receipt_abc",
        entries=[{"type": "currency", "currencyKey": "gold", "amount": 500}],
        source_ref_id="rcpt",
    )
    assert g["id"] == "g1"
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "idempotencyKey": "apple_receipt_abc",
        "kind": "reward",
        "entries": [{"type": "currency", "currencyKey": "gold", "amount": 500}],
        "sourceKind": "api",
        "sourceRefId": "rcpt",
    }


def test_grants_create_surfaces_idempotency_conflict(respx_mock, make_kraty):
    respx_mock.post(f"{BASE_URL}/server/v1/players/p/grants").mock(
        return_value=httpx.Response(
            409,
            json={"error": {"code": "idempotency_conflict", "message": "same key, different body"}},
        )
    )
    k = make_kraty()
    with pytest.raises(KratyServerError) as exc_info:
        k.grants.create(
            "p",
            idempotency_key="rcpt",
            entries=[{"type": "currency", "currencyKey": "gold", "amount": 1}],
        )
    assert exc_info.value.is_idempotency_conflict is True


def test_grants_ack_posts_to_right_url(respx_mock, make_kraty):
    route = respx_mock.post(f"{BASE_URL}/server/v1/players/p/grants/g1/ack").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "id": "g1",
                    "kind": "reward",
                    "contents": {},
                    "sourceKind": "api",
                    "sourceRefId": None,
                    "parentGrantId": None,
                    "status": "claimed",
                    "rolledAt": None,
                    "claimedAt": "2026-01-01T00:00:00Z",
                    "expiresAt": None,
                    "createdAt": "2026-01-01",
                }
            },
        )
    )
    k = make_kraty()
    g = k.grants.ack("p", "g1")
    assert g["status"] == "claimed"
    assert route.call_count == 1


# ─── InventoryClient ────────────────────────────────────────────────


def test_inventory_grant_posts_to_inventory_grant(respx_mock, make_kraty):
    route = respx_mock.post(
        f"{BASE_URL}/server/v1/players/player_42/inventory/starter_chest/grant"
    ).mock(
        return_value=httpx.Response(
            200, json={"data": {"itemKey": "starter_chest", "quantity": 1, "applied": True}}
        )
    )
    k = make_kraty()
    res = k.inventory.grant(
        "player_42",
        "starter_chest",
        quantity=1,
        reason="iap",
        idempotency_key="rcpt",
    )
    assert res["applied"] is True
    body = json.loads(route.calls[0].request.content)
    assert body == {"quantity": 1, "reason": "iap", "idempotencyKey": "rcpt"}


def test_inventory_revoke_posts_to_inventory_revoke(respx_mock, make_kraty):
    route = respx_mock.post(
        f"{BASE_URL}/server/v1/players/p/inventory/sword/revoke"
    ).mock(
        return_value=httpx.Response(200, json={"data": {"itemKey": "sword", "quantity": 0, "applied": True}})
    )
    k = make_kraty()
    k.inventory.revoke("p", "sword", quantity=1, reason="chargeback")
    body = json.loads(route.calls[0].request.content)
    assert body["quantity"] == 1
    assert body["reason"] == "chargeback"
    assert body["idempotencyKey"] == "idem-1"  # auto-stamped


# ─── WalletClient ───────────────────────────────────────────────────


def test_wallet_credit_posts_amount(respx_mock, make_kraty):
    route = respx_mock.post(f"{BASE_URL}/server/v1/players/player_42/wallet/gold/credit").mock(
        return_value=httpx.Response(
            200, json={"data": {"economyKey": "gold", "balance": 600, "applied": True}}
        ),
    )
    k = make_kraty()
    res = k.wallet.credit(
        "player_42",
        "gold",
        amount=500,
        reason="iap",
        idempotency_key="rcpt_xyz",
    )
    assert res["balance"] == 600
    body = json.loads(route.calls[0].request.content)
    assert body == {"amount": 500, "reason": "iap", "idempotencyKey": "rcpt_xyz"}


def test_wallet_debit_posts_to_debit_url(respx_mock, make_kraty):
    route = respx_mock.post(f"{BASE_URL}/server/v1/players/player_42/wallet/gold/debit").mock(
        return_value=httpx.Response(
            200, json={"data": {"economyKey": "gold", "balance": 400, "applied": True}}
        ),
    )
    k = make_kraty()
    k.wallet.debit("player_42", "gold", amount=100, reason="refund")
    assert route.call_count == 1


# ─── LobbiesClient ──────────────────────────────────────────────────


def test_lobbies_push_creates_with_roster_and_key(respx_mock, make_kraty):
    route = respx_mock.post(
        f"{BASE_URL}/server/v1/games/game_1/events/quick_brawl/lobbies"
    ).mock(
        return_value=httpx.Response(
            201,
            json={
                "data": {
                    "id": "lob1",
                    "eventId": "e1",
                    "eventWindowId": "w1",
                    "leaderboardId": "lb1",
                    "mode": "lobby_matched",
                    "status": "active",
                    "capacity": 4,
                    "fillBy": None,
                    "participantCount": 2,
                    "botSlots": 0,
                    "startedAt": None,
                    "endsAt": None,
                }
            },
        )
    )
    k = make_kraty()
    lobby = k.lobbies.push(
        "game_1",
        "quick_brawl",
        key="matchmaker_lobby_123",
        external_player_ids=["alice", "bob"],
        capacity=4,
    )
    assert lobby["id"] == "lob1"
    body = json.loads(route.calls[0].request.content)
    assert body["key"] == "matchmaker_lobby_123"
    assert body["externalPlayerIds"] == ["alice", "bob"]
    assert body["capacity"] == 4


def test_lobbies_read_gets_from_games_lobbies(respx_mock, make_kraty):
    route = respx_mock.get(f"{BASE_URL}/server/v1/games/game_1/lobbies/lob1").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "id": "lob1",
                    "eventId": "e1",
                    "eventWindowId": "w1",
                    "leaderboardId": "lb1",
                    "mode": "lobby_matched",
                    "status": "active",
                    "capacity": 4,
                    "fillBy": None,
                    "participantCount": 2,
                    "botSlots": 0,
                    "startedAt": None,
                    "endsAt": None,
                }
            },
        )
    )
    k = make_kraty()
    k.lobbies.read("game_1", "lob1")
    assert route.call_count == 1
    assert route.calls[0].request.method == "GET"


# ─── PlayersClient ──────────────────────────────────────────────────


def test_players_get_returns_unified_snapshot(respx_mock, make_kraty):
    respx_mock.get(f"{BASE_URL}/server/v1/players/alice").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "player": {
                        "id": "p1",
                        "externalPlayerId": "alice",
                        "studioId": "s1",
                        "gameId": "g1",
                        "createdAt": "2026-01-01",
                        "updatedAt": "2026-01-01",
                    },
                    "inventory": [
                        {
                            "itemKey": "potion",
                            "quantity": 3,
                            "metadata": {},
                            "createdAt": "2026-01-01",
                            "updatedAt": "2026-01-01",
                        }
                    ],
                    "wallet": [
                        {
                            "economyKey": "gold",
                            "balance": 100,
                            "metadata": {},
                            "createdAt": "2026-01-01",
                            "updatedAt": "2026-01-01",
                        }
                    ],
                    "recentGrants": [],
                }
            },
        )
    )
    k = make_kraty()
    snap = k.players.get("alice")
    assert snap["player"]["externalPlayerId"] == "alice"
    assert len(snap["inventory"]) == 1
    assert snap["wallet"][0]["balance"] == 100


# ─── PlayersClient — GDPR delete + export ───────────────────────────


def test_players_delete_posts_reason_and_returns_outcome(respx_mock, make_kraty):
    route = respx_mock.post(f"{BASE_URL}/server/v1/players/alice/delete").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "playerId": "p1",
                    "externalPlayerId": "alice",
                    "anonymizedExternalId": "__deleted_abc-123__",
                    "deletedAt": "2026-06-11T10:00:00Z",
                    "attemptsAnonymized": 12,
                    "lobbiesAnonymized": 3,
                    "leaderboardsScrubbed": 4,
                    "status": "erased",
                }
            },
        )
    )
    k = make_kraty()
    out = k.players.delete("alice", reason="gdpr_erasure")
    assert out["status"] == "erased"
    assert out["anonymizedExternalId"].startswith("__deleted_")
    body = json.loads(route.calls[0].request.content)
    assert body["reason"] == "gdpr_erasure"


def test_players_delete_for_unknown_player_returns_no_op(respx_mock, make_kraty):
    respx_mock.post(f"{BASE_URL}/server/v1/players/ghost/delete").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "playerId": None,
                    "externalPlayerId": "ghost",
                    "anonymizedExternalId": None,
                    "deletedAt": "2026-06-11T10:00:00Z",
                    "attemptsAnonymized": 0,
                    "lobbiesAnonymized": 0,
                    "leaderboardsScrubbed": 0,
                    "status": "no_op_never_existed",
                }
            },
        )
    )
    k = make_kraty()
    out = k.players.delete("ghost")
    assert out["status"] == "no_op_never_existed"
    assert out["playerId"] is None


def test_players_export_gets_full_bundle(respx_mock, make_kraty):
    respx_mock.get(f"{BASE_URL}/server/v1/players/alice/export").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "schemaVersion": 1,
                    "exportedAt": "2026-06-11T10:00:00Z",
                    "player": {
                        "id": "p1",
                        "externalPlayerId": "alice",
                        "studioId": "s1",
                        "gameId": "g1",
                        "firstSeenAt": "2026-01-01T00:00:00Z",
                        "lastSeenAt": "2026-06-10T12:00:00Z",
                        "lastContextSnapshot": {"country": "PT"},
                        "registeredAt": "2026-01-01T00:00:00Z",
                        "secretRotatedAt": None,
                        "deletedAt": None,
                    },
                    "attempts": [{"id": "att1", "status": "completed"}],
                    "grants": [],
                    "inventory": [{"itemKey": "potion", "quantity": 3}],
                    "wallet": [{"economyKey": "gold", "balance": 500}],
                    "lobbies": [],
                }
            },
        )
    )
    k = make_kraty()
    exp = k.players.export("alice")
    assert exp["schemaVersion"] == 1
    assert exp["player"]["externalPlayerId"] == "alice"
    assert len(exp["attempts"]) == 1


def test_players_export_surfaces_not_found(respx_mock, make_kraty):
    respx_mock.get(f"{BASE_URL}/server/v1/players/ghost/export").mock(
        return_value=httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "Player 'ghost' not found"}},
        )
    )
    k = make_kraty()
    with pytest.raises(KratyServerError) as exc_info:
        k.players.export("ghost")
    assert exc_info.value.is_not_found is True


# ─── MigrateClient ──────────────────────────────────────────────────


def test_migrate_players_posts_rows_envelope(respx_mock, make_kraty):
    route = respx_mock.post(f"{BASE_URL}/server/v1/migrate/players").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"applied": 2, "skipped": 0, "failed": 0, "failures": []}},
        )
    )
    k = make_kraty()
    rows = [
        {"externalPlayerId": "p_1", "idempotencyKey": "p_1"},
        {"externalPlayerId": "p_2", "idempotencyKey": "p_2", "contextSnapshot": {"country": "PT"}},
    ]
    out = k.migrate.players(rows)
    assert out["applied"] == 2
    body = json.loads(route.calls[0].request.content)
    assert body["rows"] == rows


def test_migrate_wallet_posts_amount_per_row(respx_mock, make_kraty):
    respx_mock.post(f"{BASE_URL}/server/v1/migrate/wallet").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"applied": 1, "skipped": 0, "failed": 0, "failures": []}},
        )
    )
    k = make_kraty()
    out = k.migrate.wallet(
        [{"externalPlayerId": "p_1", "economyKey": "gold", "amount": 500, "idempotencyKey": "p_1:gold"}]
    )
    assert out["applied"] == 1


def test_migrate_inventory_returns_failures_for_bad_rows(respx_mock, make_kraty):
    respx_mock.post(f"{BASE_URL}/server/v1/migrate/inventory").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "applied": 1,
                    "skipped": 0,
                    "failed": 1,
                    "failures": [
                        {
                            "rowIndex": 1,
                            "externalPlayerId": "p_2",
                            "error": {"code": "unknown_item", "message": "item not found"},
                        }
                    ],
                }
            },
        )
    )
    k = make_kraty()
    out = k.migrate.inventory(
        [
            {"externalPlayerId": "p_1", "itemKey": "potion", "quantity": 3, "idempotencyKey": "p_1:potion"},
            {"externalPlayerId": "p_2", "itemKey": "gone", "quantity": 1, "idempotencyKey": "p_2:gone"},
        ]
    )
    assert out["failed"] == 1
    assert out["failures"][0]["error"]["code"] == "unknown_item"


# ─── HealthClient ───────────────────────────────────────────────────


def test_health_ping_returns_key_info(respx_mock, make_kraty):
    respx_mock.get(f"{BASE_URL}/server/v1/ping").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "apiKey": {
                    "id": "k1",
                    "prefix": "sUUVdrM8",
                    "permissionSet": "server_integration",
                    "environment": "live",
                    "studioId": "s1",
                    "gameId": "g1",
                },
            },
        )
    )
    k = make_kraty()
    p = k.health.ping()
    assert p["ok"] is True
    assert p["apiKey"]["permissionSet"] == "server_integration"
