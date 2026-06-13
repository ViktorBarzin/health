"""Connections API — list / connect / sync / disconnect, per-user scoped (connections).

DB-backed (real Postgres) and **never hits the network** — the Oura HTTP call goes
through the real OuraConnector with an injected ``httpx.MockTransport`` (same
no-network discipline as the OFF tests). Pins the security-critical + scoping
contract from the acceptance criteria:

* the **token is write-only**: it is accepted on connect but NEVER appears in any
  response body (list, connect, sync, or detail) — asserted by scanning the whole
  serialized response for the secret;
* **per-user scoping**: a user can't sync or disconnect another user's Connection
  (404, no leak);
* connect → sync lands data and reports status/last-sync; an invalid token
  surfaces ``status=error`` without crashing;
* when no encryption key is configured the API fails closed with a clear 503
  (never stores a token unprotected).
"""

import datetime as dt

import httpx
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.connection import Connection, ConnectionProvider
from app.models.user import User

_KEY = Fernet.generate_key().decode()
_TOKEN = "OURA-PAT-API-SECRET-9f8e7d6c5b4a3210"

_OURA_SLEEP = {
    "data": [
        {
            "id": "n1",
            "day": "2026-06-10",
            "bedtime_start": "2026-06-09T23:30:00+00:00",
            "bedtime_end": "2026-06-10T07:30:00+00:00",
            "average_hrv": 64,
            "average_heart_rate": 57.0,
            "lowest_heart_rate": 49,
            "total_sleep_duration": 27000,
            "type": "long_sleep",
        }
    ],
    "next_token": None,
}


async def _make_user(db, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


@pytest.fixture(autouse=True)
def _configure_key(monkeypatch):
    """Configure an encryption key for the API's cipher dependency by default."""
    from app.config import settings

    monkeypatch.setattr(settings, "CONNECTION_ENCRYPTION_KEY", _KEY)


@pytest.fixture
def mock_oura(monkeypatch):
    """Point the registered OuraConnector at a MockTransport (no network).

    Returns a setter so a test can choose the response (success or an auth error).
    """
    from app.services import connectors

    def _set(payload, *, status=200):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, json=payload)

        connectors._REGISTRY[ConnectionProvider.oura]._transport = httpx.MockTransport(
            handler
        )

    yield _set
    # Reset so the real connector has no leftover transport.
    connectors._REGISTRY[ConnectionProvider.oura]._transport = None


@pytest.fixture
async def client(db_session):
    state = {"user": None}

    async def _override_db():
        yield db_session

    async def _override_user():
        return state["user"]

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.set_user = lambda u: state.__setitem__("user", u)  # type: ignore[attr-defined]
        yield ac
    app.dependency_overrides.clear()


# --------------------------------------------------------------------------- #
# List available providers + state
# --------------------------------------------------------------------------- #


async def test_list_shows_available_providers_with_disconnected_state(client, db_session):
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)

    resp = await client.get("/api/connections")
    assert resp.status_code == 200
    body = resp.json()
    providers = {p["provider"] for p in body}
    assert "oura" in providers
    oura = next(p for p in body if p["provider"] == "oura")
    assert oura["connected"] is False
    # A "where to get the token" link is exposed for the UI.
    assert "ouraring.com" in oura["instructions_url"]
    # No token / credential field anywhere.
    assert "token" not in oura
    assert "credential" not in oura
    assert "encrypted_credential" not in oura


# --------------------------------------------------------------------------- #
# Connect (paste token) — write-only
# --------------------------------------------------------------------------- #


async def test_connect_stores_token_and_never_returns_it(client, db_session):
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)

    resp = await client.post(
        "/api/connections", json={"provider": "oura", "token": _TOKEN}
    )
    assert resp.status_code in (200, 201)
    # The token must NOT be in the response anywhere.
    assert _TOKEN not in resp.text
    body = resp.json()
    assert body["provider"] == "oura"
    assert body["connected"] is True
    assert "token" not in body
    assert "credential" not in body
    assert "encrypted_credential" not in body

    # It was stored encrypted (the row's ciphertext is not the plaintext).
    conn = (
        await db_session.execute(
            select(Connection).where(Connection.user_id == alice.id)
        )
    ).scalar_one()
    assert conn.encrypted_credential != _TOKEN.encode()
    assert _TOKEN.encode() not in conn.encrypted_credential


async def test_list_after_connect_never_exposes_the_token(client, db_session):
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    await client.post("/api/connections", json={"provider": "oura", "token": _TOKEN})

    resp = await client.get("/api/connections")
    assert resp.status_code == 200
    assert _TOKEN not in resp.text
    oura = next(p for p in resp.json() if p["provider"] == "oura")
    assert oura["connected"] is True


async def test_connect_rejects_blank_token(client, db_session):
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    resp = await client.post(
        "/api/connections", json={"provider": "oura", "token": "   "}
    )
    assert resp.status_code == 422


async def test_connect_returns_503_when_encryption_not_configured(
    client, db_session, monkeypatch
):
    from app.config import settings

    monkeypatch.setattr(settings, "CONNECTION_ENCRYPTION_KEY", None)
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)

    resp = await client.post(
        "/api/connections", json={"provider": "oura", "token": _TOKEN}
    )
    assert resp.status_code == 503
    # Fail closed — nothing stored.
    count = (
        await db_session.execute(select(func.count()).select_from(Connection))
    ).scalar()
    assert count == 0


# --------------------------------------------------------------------------- #
# Sync now
# --------------------------------------------------------------------------- #


async def test_sync_now_pulls_and_reports_status(client, db_session, mock_oura):
    mock_oura(_OURA_SLEEP)
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    await client.post("/api/connections", json={"provider": "oura", "token": _TOKEN})

    resp = await client.post("/api/connections/oura/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["records_ingested"] == 3  # HRV + RHR + sleep
    assert body["last_sync_at"]
    assert body["last_error"] is None
    # Still no token in the sync response.
    assert _TOKEN not in resp.text


async def test_sync_with_invalid_token_reports_error_not_500(
    client, db_session, mock_oura
):
    mock_oura({"detail": "Unauthorized"}, status=401)
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    await client.post("/api/connections", json={"provider": "oura", "token": _TOKEN})

    resp = await client.post("/api/connections/oura/sync")
    # The endpoint succeeds (200) but reports the connection is in error.
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert body["last_error"]
    assert _TOKEN not in resp.text  # error message never leaks the token


async def test_sync_unknown_connection_is_404(client, db_session):
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)  # Alice has not connected Oura
    resp = await client.post("/api/connections/oura/sync")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Per-user scoping
# --------------------------------------------------------------------------- #


async def test_cannot_sync_another_users_connection(client, db_session):
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    client.set_user(alice)
    await client.post("/api/connections", json={"provider": "oura", "token": _TOKEN})

    # Bob tries to sync Oura — he has no Connection, so 404 (Alice's is invisible).
    client.set_user(bob)
    resp = await client.post("/api/connections/oura/sync")
    assert resp.status_code == 404


async def test_cannot_disconnect_another_users_connection(client, db_session):
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    client.set_user(alice)
    await client.post("/api/connections", json={"provider": "oura", "token": _TOKEN})

    client.set_user(bob)
    resp = await client.delete("/api/connections/oura")
    assert resp.status_code == 404

    # Alice's Connection survives.
    count = (
        await db_session.execute(select(func.count()).select_from(Connection))
    ).scalar()
    assert count == 1


async def test_disconnect_removes_own_connection(client, db_session):
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    await client.post("/api/connections", json={"provider": "oura", "token": _TOKEN})

    resp = await client.delete("/api/connections/oura")
    assert resp.status_code == 204
    count = (
        await db_session.execute(select(func.count()).select_from(Connection))
    ).scalar()
    assert count == 0


async def test_list_only_shows_own_connection_state(client, db_session):
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    client.set_user(alice)
    await client.post("/api/connections", json={"provider": "oura", "token": _TOKEN})

    # Bob's list shows Oura as NOT connected (Alice's row is invisible to him).
    client.set_user(bob)
    resp = await client.get("/api/connections")
    oura = next(p for p in resp.json() if p["provider"] == "oura")
    assert oura["connected"] is False
