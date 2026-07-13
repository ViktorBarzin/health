"""Rest-timer Web Push (ADR-0010) — subscriptions, scheduling, delivery.

The one mechanism that reaches a locked iPhone (and, via OS mirroring, the
Apple Watch) from a PWA. Contract pinned here:

- Fail closed: with no VAPID keys configured the config endpoint reports
  disabled and the write endpoints 503 — mirroring CONNECTION_ENCRYPTION_KEY.
- Subscriptions upsert by endpoint (a re-subscribe refreshes keys, never
  duplicates) and are per-user scoped.
- One pending timer per user: scheduling replaces, skipping cancels, and
  another user's timer is untouchable.
- Delivery claims due rows exactly once (claim = delete inside the txn),
  fans out to every subscription, drops subscriptions the push service says
  are gone (404/410), and never touches future timers.
- The payload is the JSON the service worker renders: title/body/url/tag.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.push import PushSubscription, PushTimer
from app.models.user import User
from app.services.push import PushConfig, send_web_push
from app.services.push_query import deliver_due, schedule_rest_push

_CONFIG = PushConfig(
    private_key="test-private",
    public_key="test-public",
    subject="mailto:test@example.com",
)


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


@pytest.fixture
def push_enabled(monkeypatch):
    monkeypatch.setattr(settings, "PUSH_VAPID_PRIVATE_KEY", "test-private")
    monkeypatch.setattr(settings, "PUSH_VAPID_PUBLIC_KEY", "test-public")
    monkeypatch.setattr(settings, "PUSH_VAPID_SUBJECT", "mailto:test@example.com")


async def _user(db, email: str = "alice@example.com") -> User:
    u = User(email=email)
    db.add(u)
    await db.flush()
    return u


def _sub_body(endpoint: str = "https://push.example/v1/abc") -> dict:
    return {"endpoint": endpoint, "keys": {"p256dh": "pk", "auth": "ak"}}


# --------------------------------------------------------------------------- #
# Fail closed without keys
# --------------------------------------------------------------------------- #


async def test_disabled_without_keys(client, db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "PUSH_VAPID_PRIVATE_KEY", None)
    alice = await _user(db_session)
    client.set_user(alice)

    cfg = (await client.get("/api/push/config")).json()
    assert cfg == {"enabled": False, "public_key": None}

    assert (
        await client.post("/api/push/subscriptions", json=_sub_body())
    ).status_code == 503


async def test_config_exposes_public_key_when_enabled(
    client, db_session, push_enabled
) -> None:
    alice = await _user(db_session)
    client.set_user(alice)
    cfg = (await client.get("/api/push/config")).json()
    assert cfg == {"enabled": True, "public_key": "test-public"}


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #


async def test_subscribe_upserts_by_endpoint(client, db_session, push_enabled) -> None:
    alice = await _user(db_session)
    client.set_user(alice)

    assert (
        await client.post("/api/push/subscriptions", json=_sub_body())
    ).status_code == 204
    # Same endpoint, refreshed keys — updates in place, no duplicate row.
    body = _sub_body()
    body["keys"]["p256dh"] = "pk2"
    assert (await client.post("/api/push/subscriptions", json=body)).status_code == 204

    rows = (await db_session.execute(select(PushSubscription))).scalars().all()
    assert len(rows) == 1
    assert rows[0].p256dh == "pk2"
    assert rows[0].user_id == alice.id

    resp = await client.request(
        "DELETE",
        "/api/push/subscriptions",
        json={"endpoint": body["endpoint"]},
    )
    assert resp.status_code == 204
    rows = (await db_session.execute(select(PushSubscription))).scalars().all()
    assert rows == []


# --------------------------------------------------------------------------- #
# Rest-timer scheduling
# --------------------------------------------------------------------------- #


async def test_schedule_replaces_and_cancel_deletes(
    client, db_session, push_enabled
) -> None:
    alice = await _user(db_session)
    client.set_user(alice)
    fire1 = datetime.now(timezone.utc) + timedelta(seconds=90)
    fire2 = datetime.now(timezone.utc) + timedelta(seconds=150)
    sid = str(uuid.uuid4())

    for fire_at in (fire1, fire2):
        resp = await client.post(
            "/api/push/rest-timer",
            json={
                "fire_at": fire_at.isoformat(),
                "label": "Bench Press",
                "session_id": sid,
            },
        )
        assert resp.status_code == 204

    rows = (await db_session.execute(select(PushTimer))).scalars().all()
    assert len(rows) == 1  # one pending per user — the second replaced the first
    assert abs((rows[0].fire_at - fire2).total_seconds()) < 1

    assert (await client.delete("/api/push/rest-timer")).status_code == 204
    assert (await db_session.execute(select(PushTimer))).scalars().all() == []
    # Cancelling with nothing pending stays a 204 (idempotent).
    assert (await client.delete("/api/push/rest-timer")).status_code == 204


async def test_schedule_rejects_out_of_range_fire_at(
    client, db_session, push_enabled
) -> None:
    alice = await _user(db_session)
    client.set_user(alice)
    for bad in (
        datetime.now(timezone.utc) - timedelta(minutes=5),
        datetime.now(timezone.utc) + timedelta(hours=2),
    ):
        resp = await client.post(
            "/api/push/rest-timer",
            json={"fire_at": bad.isoformat(), "label": "x", "session_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Delivery
# --------------------------------------------------------------------------- #


class _RecordingSender:
    """A fake pywebpush.webpush recording calls; scripted per-endpoint failures."""

    def __init__(self, gone_endpoints: set[str] | None = None):
        self.sent: list[tuple[str, str]] = []  # (endpoint, data)
        self.gone = gone_endpoints or set()

    def __call__(self, subscription_info, data, **kwargs):
        endpoint = subscription_info["endpoint"]
        if endpoint in self.gone:
            from pywebpush import WebPushException

            class _Resp:
                status_code = 410

            raise WebPushException("gone", response=_Resp())
        self.sent.append((endpoint, data))


async def test_deliver_due_sends_clears_and_is_exclusive(db_session) -> None:
    alice = await _user(db_session)
    db_session.add(
        PushSubscription(
            user_id=alice.id, endpoint="https://push.example/1", p256dh="pk", auth="ak"
        )
    )
    now = datetime.now(timezone.utc)
    await schedule_rest_push(
        db_session,
        alice.id,
        fire_at=now - timedelta(seconds=1),
        title="Rest over",
        body="Next: Bench Press",
        url="/sessions/abc",
    )

    sender = _RecordingSender()
    delivered = await deliver_due(db_session, now=now, config=_CONFIG, sender=sender)
    assert delivered == 1
    assert len(sender.sent) == 1
    endpoint, data = sender.sent[0]
    payload = json.loads(data)
    assert payload["title"] == "Rest over"
    assert payload["body"] == "Next: Bench Press"
    assert payload["url"] == "/sessions/abc"
    assert payload["tag"] == "rest-timer"

    # The row was claimed — a second pass sends nothing.
    assert await deliver_due(db_session, now=now, config=_CONFIG, sender=sender) == 0
    assert len(sender.sent) == 1


async def test_deliver_due_skips_future_timers(db_session) -> None:
    alice = await _user(db_session)
    db_session.add(
        PushSubscription(
            user_id=alice.id, endpoint="https://push.example/1", p256dh="pk", auth="ak"
        )
    )
    now = datetime.now(timezone.utc)
    await schedule_rest_push(
        db_session,
        alice.id,
        fire_at=now + timedelta(seconds=60),
        title="t",
        body="b",
        url="/",
    )
    sender = _RecordingSender()
    assert await deliver_due(db_session, now=now, config=_CONFIG, sender=sender) == 0
    assert (await db_session.execute(select(PushTimer))).scalars().all() != []


async def test_deliver_due_drops_gone_subscriptions(db_session) -> None:
    alice = await _user(db_session)
    db_session.add_all(
        [
            PushSubscription(
                user_id=alice.id, endpoint="https://push.example/old", p256dh="p", auth="a"
            ),
            PushSubscription(
                user_id=alice.id, endpoint="https://push.example/new", p256dh="p", auth="a"
            ),
        ]
    )
    now = datetime.now(timezone.utc)
    await schedule_rest_push(
        db_session, alice.id, fire_at=now, title="t", body="b", url="/"
    )
    sender = _RecordingSender(gone_endpoints={"https://push.example/old"})
    await deliver_due(db_session, now=now, config=_CONFIG, sender=sender)

    remaining = (await db_session.execute(select(PushSubscription))).scalars().all()
    assert [s.endpoint for s in remaining] == ["https://push.example/new"]
    # The healthy endpoint still got its push.
    assert [e for e, _ in sender.sent] == ["https://push.example/new"]


def test_send_web_push_maps_results() -> None:
    ok = send_web_push(
        {"endpoint": "e", "keys": {}}, "data", _CONFIG, sender=lambda *a, **k: None
    )
    assert ok == "ok"

    def _gone(*a, **k):
        from pywebpush import WebPushException

        class _Resp:
            status_code = 404

        raise WebPushException("nope", response=_Resp())

    assert send_web_push({"endpoint": "e", "keys": {}}, "d", _CONFIG, sender=_gone) == "gone"

    def _boom(*a, **k):
        raise RuntimeError("network down")

    assert send_web_push({"endpoint": "e", "keys": {}}, "d", _CONFIG, sender=_boom) == "error"
