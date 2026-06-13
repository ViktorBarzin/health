"""Identity dependency contract (ADR-0003): the app is authenticated solely
from the Authentik forward-auth ``X-authentik-email`` header, with a
``DEV_AUTH_EMAIL`` env override for local docker-compose use.

- header present  -> resolves/creates the user by email
- first-seen email -> auto-provisions a user row
- no header, no override -> 401
- DEV_AUTH_EMAIL set and no header -> uses the override
- header always wins over the dev override
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from starlette.datastructures import Headers
from starlette.requests import Request

from app.config import Settings
from app.core.dependencies import get_current_user
from app.models.user import User


def _request(headers: dict[str, str]) -> Request:
    """A minimal ASGI Request carrying the given headers."""
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw})


async def _count_users(db) -> int:
    return (await db.execute(select(func.count()).select_from(User))).scalar_one()


async def test_header_resolves_and_provisions_user(db_session) -> None:
    settings = Settings(DATABASE_URL="x")
    req = _request({"X-authentik-email": "newcomer@example.com"})

    user = await get_current_user(req, db=db_session, settings=settings)

    assert user.email == "newcomer@example.com"
    assert user.id is not None
    assert await _count_users(db_session) == 1


async def test_existing_user_is_reused_not_duplicated(db_session) -> None:
    settings = Settings(DATABASE_URL="x")
    existing = User(email="repeat@example.com")
    db_session.add(existing)
    await db_session.flush()

    req = _request({"X-authentik-email": "repeat@example.com"})
    user = await get_current_user(req, db=db_session, settings=settings)

    assert user.id == existing.id
    assert await _count_users(db_session) == 1


async def test_missing_header_and_no_dev_override_is_401(db_session) -> None:
    settings = Settings(DATABASE_URL="x")
    req = _request({})

    with pytest.raises(HTTPException) as exc:
        await get_current_user(req, db=db_session, settings=settings)
    assert exc.value.status_code == 401


async def test_dev_auth_email_override_used_when_no_header(db_session) -> None:
    settings = Settings(DATABASE_URL="x", DEV_AUTH_EMAIL="dev@example.com")
    req = _request({})

    user = await get_current_user(req, db=db_session, settings=settings)

    assert user.email == "dev@example.com"
    assert await _count_users(db_session) == 1


async def test_header_takes_precedence_over_dev_override(db_session) -> None:
    settings = Settings(DATABASE_URL="x", DEV_AUTH_EMAIL="dev@example.com")
    req = _request({"X-authentik-email": "real@example.com"})

    user = await get_current_user(req, db=db_session, settings=settings)

    assert user.email == "real@example.com"


async def test_email_is_normalised_lowercase_and_trimmed(db_session) -> None:
    settings = Settings(DATABASE_URL="x")
    req = _request({"X-authentik-email": "  Mixed.Case@Example.com  "})

    user = await get_current_user(req, db=db_session, settings=settings)

    assert user.email == "mixed.case@example.com"
    # Same identity arriving differently-cased must not create a second row.
    req2 = _request({"X-authentik-email": "mixed.case@example.com"})
    user2 = await get_current_user(req2, db=db_session, settings=settings)
    assert user2.id == user.id
    assert await _count_users(db_session) == 1


async def test_blank_header_falls_back_to_401(db_session) -> None:
    settings = Settings(DATABASE_URL="x")
    req = _request({"X-authentik-email": "   "})

    with pytest.raises(HTTPException) as exc:
        await get_current_user(req, db=db_session, settings=settings)
    assert exc.value.status_code == 401
