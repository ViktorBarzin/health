"""Web Push sending core (ADR-0010) — VAPID config + one-shot send.

Thin, injectable wrapper over :func:`pywebpush.webpush` so everything above it
(the query layer, the poller, the API) is testable with a fake sender and no
network. Configuration mirrors ``CONNECTION_ENCRYPTION_KEY``'s fail-closed
posture: all three ``PUSH_VAPID_*`` settings present ⇒ enabled; anything
missing ⇒ the feature is off and the API says so with a 503 — never a
half-configured sender.

Key generation (deploy-time, once):
``vapid --gen`` (py-vapid CLI) or any P-256 keypair; store the URL-safe base64
private key + the uncompressed-point public key (the browser's
``applicationServerKey``) in Vault ``secret/health-push`` and expose them as
``PUSH_VAPID_PRIVATE_KEY`` / ``PUSH_VAPID_PUBLIC_KEY``, with
``PUSH_VAPID_SUBJECT`` a ``mailto:`` contact per RFC 8292.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from pywebpush import WebPushException, webpush

from app.config import Settings

#: Push-service statuses meaning "this subscription no longer exists" — the
#: caller should delete the subscription row (the browser unsubscribed or the
#: PWA was uninstalled).
_GONE_STATUSES = frozenset({404, 410})

SendResult = Literal["ok", "gone", "error"]

#: The pywebpush-compatible callable shape, injectable for tests.
Sender = Callable[..., object]


@dataclass(frozen=True)
class PushConfig:
    """The VAPID identity this server signs pushes with."""

    private_key: str
    public_key: str
    subject: str


def push_config(settings: Settings) -> PushConfig | None:
    """The configured VAPID identity, or None when push is (fail-closed) off."""
    private = settings.PUSH_VAPID_PRIVATE_KEY
    public = settings.PUSH_VAPID_PUBLIC_KEY
    subject = settings.PUSH_VAPID_SUBJECT
    if not private or not public or not subject:
        return None
    return PushConfig(private_key=private, public_key=public, subject=subject)


def rest_timer_payload(title: str, body: str, url: str) -> str:
    """The JSON document the service worker's push handler renders.

    ``tag`` is fixed so a newer rest notification replaces a stale one instead
    of stacking (the OS collapses same-tag notifications).
    """
    return json.dumps({"title": title, "body": body, "url": url, "tag": "rest-timer"})


def send_web_push(
    subscription_info: dict,
    data: str,
    config: PushConfig,
    *,
    sender: Sender = webpush,
) -> SendResult:
    """Send one push; classify the outcome instead of raising.

    ``gone`` ⇒ the push service says the subscription is dead (delete it);
    ``error`` ⇒ transient/other failure (keep the subscription, drop this
    send — a rest cue is worthless a minute late, so there are no retries).
    """
    try:
        sender(
            subscription_info=subscription_info,
            data=data,
            vapid_private_key=config.private_key,
            vapid_claims={"sub": config.subject},
            ttl=120,
        )
        return "ok"
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in _GONE_STATUSES:
            return "gone"
        return "error"
    except Exception:
        return "error"
