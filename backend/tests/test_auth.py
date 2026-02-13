"""Tests for the /api/auth endpoints."""

import pytest

from app.core.rate_limit import _request_log


@pytest.fixture(autouse=True)
def clear_rate_limit():
    """Clear the rate limiter between every test."""
    _request_log.clear()
    yield
    _request_log.clear()


@pytest.fixture(autouse=True)
def enable_test_mode():
    """Enable TEST_MODE for all auth tests so the test-login endpoint works."""
    from app.config import settings

    original = settings.TEST_MODE
    settings.TEST_MODE = True
    yield
    settings.TEST_MODE = original


# ---------------------------------------------------------------------------
# Login begin / complete
# ---------------------------------------------------------------------------


async def test_login_begin_returns_challenge(client):
    """POST /api/auth/login/begin returns a challenge_id and options."""
    resp = await client.post("/api/auth/login/begin")
    assert resp.status_code == 200
    body = resp.json()
    assert "challenge_id" in body
    assert "options" in body
    assert "challenge" in body["options"]


async def test_login_complete_invalid_credential_returns_401(client):
    """POST /api/auth/login/complete with a bogus credential returns 400 (no challenge)."""
    resp = await client.post(
        "/api/auth/login/complete",
        json={
            "challenge_id": "nonexistent",
            "credential": {"id": "fake", "rawId": "fake", "response": {}},
        },
    )
    # Challenge not found -> 400
    assert resp.status_code == 400
    body = resp.json()
    assert "detail" in body
    # Must NOT leak internal exception details
    assert "Traceback" not in body["detail"]


# ---------------------------------------------------------------------------
# Register begin / complete
# ---------------------------------------------------------------------------


async def test_register_begin_creates_user(client):
    """POST /api/auth/register/begin creates a user and returns options."""
    resp = await client.post(
        "/api/auth/register/begin",
        json={"email": "newuser@example.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "options" in body
    assert "challenge" in body["options"]


async def test_register_complete_invalid_credential_returns_400(client):
    """POST /api/auth/register/complete with a bogus credential returns 400."""
    # First begin registration to store a challenge
    begin_resp = await client.post(
        "/api/auth/register/begin",
        json={"email": "reguser@example.com"},
    )
    assert begin_resp.status_code == 200

    # Attempt complete with bad credential
    resp = await client.post(
        "/api/auth/register/complete",
        json={
            "email": "reguser@example.com",
            "credential": {
                "id": "fake",
                "rawId": "fake",
                "response": {
                    "attestationObject": "AAAA",
                    "clientDataJSON": "AAAA",
                },
                "type": "public-key",
            },
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert "detail" in body
    assert "Traceback" not in body["detail"]


# ---------------------------------------------------------------------------
# Test-login endpoint
# ---------------------------------------------------------------------------


async def test_test_login_works(client):
    """POST /api/auth/test-login authenticates and sets session cookie."""
    resp = await client.post(
        "/api/auth/test-login",
        json={"email": "testuser@example.com"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "testuser@example.com"
    assert "id" in body
    # Session cookie should be set
    assert "session" in resp.cookies


async def test_test_login_creates_user_if_not_exists(client):
    """test-login creates a new user when the email does not exist yet."""
    email = "brand-new@example.com"
    resp = await client.post(
        "/api/auth/test-login",
        json={"email": email},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == email


# ---------------------------------------------------------------------------
# /me endpoint
# ---------------------------------------------------------------------------


async def test_me_returns_user_when_authenticated(authenticated_client):
    """GET /api/auth/me returns the current user when authenticated."""
    resp = await authenticated_client.get("/api/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "test@example.com"
    assert "id" in body


async def test_me_returns_401_when_not_authenticated(client):
    """GET /api/auth/me returns 401 without a session cookie."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


async def test_logout_clears_session(authenticated_client):
    """POST /api/auth/logout removes the session cookie."""
    resp = await authenticated_client.post("/api/auth/logout")
    assert resp.status_code == 204

    # Subsequent /me should fail
    me_resp = await authenticated_client.get("/api/auth/me")
    assert me_resp.status_code == 401


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


async def test_rate_limit_11th_request_returns_429(client):
    """After 10 requests to a rate-limited endpoint, the 11th returns 429."""
    for i in range(10):
        resp = await client.post("/api/auth/login/begin")
        assert resp.status_code == 200, f"Request {i+1} failed unexpectedly"

    # 11th request should be rate-limited
    resp = await client.post("/api/auth/login/begin")
    assert resp.status_code == 429
    assert "Too many requests" in resp.json()["detail"]
