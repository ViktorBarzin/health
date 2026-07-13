"""Web Push API (ADR-0010) — /api/push.

The rest timer's locked-phone (and mirrored Apple Watch) path. Everything is
per-user scoped; the write endpoints fail closed with a 503 while the VAPID
keys aren't deployed (the config endpoint tells the client so it can hide the
toggle instead of dead-ending the user at a permission prompt).
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.push import (
    PushConfigRead,
    RestTimerSchedule,
    SubscriptionCreate,
    SubscriptionDelete,
)
from app.services.push import PushConfig, push_config
from app.services.push_query import (
    cancel_rest_push,
    remove_subscription,
    schedule_rest_push,
    upsert_subscription,
)

router = APIRouter()

# A rest between sets is minutes, not hours: the schedule window tolerates a
# little clock skew backwards and caps forward at an hour so a client bug can't
# park a buzz for next Tuesday.
_PAST_GRACE = timedelta(seconds=30)
_MAX_AHEAD = timedelta(hours=1)


def _require_config() -> PushConfig:
    config = push_config(settings)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push notifications are not configured on this server",
        )
    return config


@router.get("/config", response_model=PushConfigRead)
async def read_config(user: User = Depends(get_current_user)) -> PushConfigRead:
    """Whether push is enabled, plus the applicationServerKey to subscribe with."""
    config = push_config(settings)
    if config is None:
        return PushConfigRead(enabled=False, public_key=None)
    return PushConfigRead(enabled=True, public_key=config.public_key)


@router.post("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(
    payload: SubscriptionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Store the browser's push subscription (upsert by endpoint)."""
    _require_config()
    await upsert_subscription(
        db,
        user.id,
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
    )


@router.delete("/subscriptions", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    payload: SubscriptionDelete,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Drop the caller's subscription for this endpoint (idempotent)."""
    await remove_subscription(db, user.id, endpoint=payload.endpoint)


@router.post("/rest-timer", status_code=status.HTTP_204_NO_CONTENT)
async def schedule_timer(
    payload: RestTimerSchedule,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Schedule the caller's rest-timer push (replaces any pending one).

    Fired by the client when a Set is logged while online; skipping the timer
    or logging the next Set early cancels/replaces it. Offline logging simply
    never schedules — the in-page cue still covers a lit screen (ADR-0010's
    accepted degradation).
    """
    _require_config()
    now = datetime.now(timezone.utc)
    fire_at = payload.fire_at
    if fire_at.tzinfo is None:
        fire_at = fire_at.replace(tzinfo=timezone.utc)
    if fire_at < now - _PAST_GRACE or fire_at > now + _MAX_AHEAD:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="fire_at must be within the next hour",
        )
    await schedule_rest_push(
        db,
        user.id,
        fire_at=fire_at,
        title="Rest over",
        body=f"Next: {payload.label}",
        url=f"/sessions/{payload.session_id}",
    )


@router.delete("/rest-timer", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_timer(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Cancel the caller's pending rest-timer push (idempotent)."""
    await cancel_rest_push(db, user.id)
