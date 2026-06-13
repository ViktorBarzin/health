"""FastAPI dependencies for authentication and configuration.

Identity (ADR-0003): the app is authenticated solely from the Authentik
forward-auth identity header (``X-authentik-email`` by default). Forward-auth at
the ingress overwrites any client-supplied ``X-authentik-*`` header, so the
header is trustworthy in production. For local docker-compose use, where no
Authentik sits in front, ``DEV_AUTH_EMAIL`` supplies the identity when the
header is absent. A request with neither resolves to 401.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, settings
from app.database import get_db
from app.models.user import User


def get_settings() -> Settings:
    """Return the application settings singleton."""
    return settings


def _identity_email(request: Request, settings: Settings) -> str:
    """Resolve the caller's email from the forward-auth header or dev override.

    The proxy header wins; ``DEV_AUTH_EMAIL`` is the local-dev fallback. Both are
    normalised (trimmed, lower-cased). Raises 401 when no identity is present.
    """
    raw = request.headers.get(settings.AUTH_EMAIL_HEADER) or settings.DEV_AUTH_EMAIL
    email = (raw or "").strip().lower()
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return email


async def _get_or_create_user(db: AsyncSession, email: str) -> User:
    """Return the user for ``email``, provisioning a row on first sight.

    ``users.email`` is unique; a concurrent first-sight insert can lose the race
    and raise IntegrityError — in that case the row now exists, so re-query it.
    """
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is not None:
        return user

    user = User(email=email)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        user = (
            await db.execute(select(User).where(User.email == email))
        ).scalar_one()
    return user


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    """Resolve the caller from the forward-auth identity, auto-provisioning."""
    email = _identity_email(request, settings)
    return await _get_or_create_user(db, email)
