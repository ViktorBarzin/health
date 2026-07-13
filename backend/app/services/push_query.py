"""Web Push DB glue (ADR-0010): subscriptions, the rest-timer schedule, delivery.

Delivery is the correctness-critical piece: any number of app replicas run the
poller, so a due ``push_timers`` row is **claimed with
``FOR UPDATE SKIP LOCKED`` and deleted inside the same transaction** that
sends — one buzz per timer, whichever pod gets there first, and a pod dying
mid-send loses at most that one cue (a rest notification is worthless late, so
at-most-once is the right semantics; mirrors the dedup-not-retry honesty of
the Connector sync).
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.push import PushSubscription, PushTimer
from app.services.push import PushConfig, Sender, rest_timer_payload, send_web_push
from pywebpush import webpush


async def upsert_subscription(
    db: AsyncSession, user_id: int, *, endpoint: str, p256dh: str, auth: str
) -> None:
    """Store (or refresh) one browser subscription — endpoint is the natural key.

    A re-subscribe after the browser rotated keys updates in place; a device
    handed to another account re-homes the endpoint to the new user.
    """
    stmt = pg_insert(PushSubscription).values(
        user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PushSubscription.endpoint],
        set_={"user_id": user_id, "p256dh": p256dh, "auth": auth},
    )
    await db.execute(stmt)
    await db.flush()


async def remove_subscription(db: AsyncSession, user_id: int, *, endpoint: str) -> None:
    """Delete the caller's subscription for this endpoint (idempotent)."""
    await db.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == endpoint,
        )
    )
    await db.flush()


async def schedule_rest_push(
    db: AsyncSession,
    user_id: int,
    *,
    fire_at: dt.datetime,
    title: str,
    body: str,
    url: str,
) -> None:
    """Schedule the user's rest-timer push, replacing any pending one."""
    stmt = pg_insert(PushTimer).values(
        user_id=user_id, fire_at=fire_at, title=title, body=body, url=url
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PushTimer.user_id],
        set_={"fire_at": fire_at, "title": title, "body": body, "url": url},
    )
    await db.execute(stmt)
    await db.flush()


async def cancel_rest_push(db: AsyncSession, user_id: int) -> None:
    """Drop the user's pending rest-timer push, if any (idempotent)."""
    await db.execute(delete(PushTimer).where(PushTimer.user_id == user_id))
    await db.flush()


async def deliver_due(
    db: AsyncSession,
    *,
    now: dt.datetime,
    config: PushConfig,
    sender: Sender = webpush,
) -> int:
    """Send every due timer once; returns how many timers were delivered.

    Claims due rows with SKIP LOCKED + DELETE (this transaction owns them; a
    concurrent replica skips straight past), then fans each out to all of the
    user's subscriptions. A subscription the push service reports gone
    (404/410) is deleted; transient send errors are dropped without retry.
    """
    due = (
        (
            await db.execute(
                select(PushTimer)
                .where(PushTimer.fire_at <= now)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    if not due:
        return 0

    delivered = 0
    for timer in due:
        subs = (
            (
                await db.execute(
                    select(PushSubscription).where(
                        PushSubscription.user_id == timer.user_id
                    )
                )
            )
            .scalars()
            .all()
        )
        payload = rest_timer_payload(timer.title, timer.body, timer.url)
        for sub in subs:
            result = send_web_push(
                {
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                payload,
                config,
                sender=sender,
            )
            if result == "gone":
                await db.delete(sub)
        await db.delete(timer)
        delivered += 1
    await db.flush()
    return delivered
