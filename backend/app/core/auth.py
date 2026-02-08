"""Authentication utilities: challenge store and session management."""

import secrets
import time

from app.config import settings

# In-memory session store: token -> {"user_id": int, "created_at": float}
_sessions: dict[str, dict] = {}

# In-memory challenge store: key -> (challenge_bytes, expiry_timestamp)
_challenges: dict[str, tuple[bytes, float]] = {}

_CHALLENGE_TTL = 300  # 5 minutes


def store_challenge(key: str, challenge: bytes) -> None:
    """Store a WebAuthn challenge with a 5-minute TTL."""
    _challenges[key] = (challenge, time.time() + _CHALLENGE_TTL)


def get_challenge(key: str) -> bytes | None:
    """Pop and return the stored challenge, or None if expired/missing."""
    entry = _challenges.pop(key, None)
    if entry is None:
        return None
    challenge, expiry = entry
    if time.time() > expiry:
        return None
    return challenge


def create_session(user_id: int) -> str:
    """Create a new session for the given user and return the token."""
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "user_id": user_id,
        "created_at": time.time(),
    }
    return token


def get_session(token: str) -> dict | None:
    """Look up a session by token. Returns None if expired or not found."""
    session = _sessions.get(token)
    if session is None:
        return None
    elapsed = time.time() - session["created_at"]
    if elapsed > settings.SESSION_MAX_AGE:
        _sessions.pop(token, None)
        return None
    return session


def delete_session(token: str) -> None:
    """Remove a session by token."""
    _sessions.pop(token, None)


def set_session_cookie(response, token: str) -> None:
    """Set the session cookie on a response with configurable secure flag."""
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        max_age=60 * 60 * 24 * 7,
    )
