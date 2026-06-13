"""Scheduled-pull entrypoint — sync every active Connection (connections, ADR-0006).

The **scheduled-puller** kind from ADR-0006: a job that polls each user's
connected provider on a cadence. This is the callable a **Kubernetes CronJob**
invokes; it opens a DB session, builds the credential cipher, and runs
:func:`app.services.connection_query.sync_all_active`, which pulls each ``active``
Connection independently (one failure can't abort the others) and lands new
samples idempotently.

Run it manually (or from the CronJob) exactly like the seed modules:

    python -m app.services.connection_sync_cli

Requires ``CONNECTION_ENCRYPTION_KEY`` to be set (the same key the API uses to
decrypt each user's stored token). With no key it exits without doing anything
(fail closed) — there is nothing it could decrypt.

Infra (HITL — NOT created here)
==============================
The CronJob manifest itself is infrastructure (GitOps via Terraform/Terragrunt),
so it is left as a documented stub for a human to add — see
``docs/connectors/oura-cronjob.md``. The shape:

    kind: CronJob
    spec:
      schedule: "0 * * * *"            # hourly is plenty for daily recovery data
      jobTemplate: { ... }
        image: viktorbarzin/health:latest
        command: ["python", "-m", "app.services.connection_sync_cli"]
        env:
          - DATABASE_URL (same as the app)
          - CONNECTION_ENCRYPTION_KEY (from Vault secret/health-connection-key)

The command works and is tested today; only the manifest is deferred.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging

from app.database import async_session
from app.services.connection_query import sync_all_active
from app.services.crypto import CredentialCipher

log = logging.getLogger(__name__)


async def run_scheduled_sync() -> int:
    """Sync all active Connections once; return how many synced successfully.

    The function a CronJob (or a test) calls. Returns 0 immediately when no
    encryption key is configured — there is nothing to decrypt.
    """
    cipher = CredentialCipher.from_settings()
    if cipher is None:
        log.warning(
            "CONNECTION_ENCRYPTION_KEY is not set — skipping scheduled sync "
            "(no credentials can be decrypted)."
        )
        return 0

    now = dt.datetime.now(dt.timezone.utc)
    async with async_session() as session:
        return await sync_all_active(session, cipher=cipher, now=now)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    synced = asyncio.run(run_scheduled_sync())
    print(f"Scheduled Connection sync complete: {synced} connection(s) synced.")


if __name__ == "__main__":
    main()
