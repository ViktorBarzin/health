"""Pydantic schemas for Web Push (ADR-0010) — subscriptions + rest-timer."""

import datetime as dt
import uuid

from pydantic import BaseModel, Field


class PushConfigRead(BaseModel):
    """Whether push is configured server-side, and the applicationServerKey.

    ``enabled: false`` ⇒ the client hides the notifications toggle entirely
    (VAPID keys aren't deployed — fail closed, nothing to subscribe against).
    """

    enabled: bool
    public_key: str | None = None


class SubscriptionKeys(BaseModel):
    """The browser subscription's encryption keys, verbatim from PushManager."""

    p256dh: str = Field(min_length=1, max_length=512)
    auth: str = Field(min_length=1, max_length=512)

    model_config = {"extra": "ignore"}


class SubscriptionCreate(BaseModel):
    """POST body: the PushSubscription.toJSON() the browser handed us."""

    endpoint: str = Field(min_length=1, max_length=2048)
    keys: SubscriptionKeys

    model_config = {"extra": "ignore"}


class SubscriptionDelete(BaseModel):
    """DELETE body: which of the caller's subscriptions to drop."""

    endpoint: str = Field(min_length=1, max_length=2048)

    model_config = {"extra": "forbid"}


class RestTimerSchedule(BaseModel):
    """Schedule the caller's single pending rest-timer push.

    ``fire_at`` is the countdown's end instant (client-computed — the client
    owns the timer; the server just fires the locked-phone cue). ``label`` is
    the next-up exercise line; ``session_id`` builds the tap-through URL.
    """

    fire_at: dt.datetime
    label: str = Field(min_length=1, max_length=120)
    session_id: uuid.UUID

    model_config = {"extra": "forbid"}
