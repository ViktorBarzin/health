"""Scheduled-pull entrypoint — the CronJob callable (connections, ADR-0006).

`run_scheduled_sync` is what a K8s CronJob invokes. These pin:

* the **fail-closed** short-circuit — with no ``CONNECTION_ENCRYPTION_KEY`` it does
  nothing (returns 0) rather than erroring;
* the **happy path** — with a key it opens a session and syncs every active
  Connection (here proven by counting landed records), never hitting the network
  (the connector factory is mocked).
"""

import contextlib
import datetime as dt

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from app.models.connection import ConnectionProvider
from app.models.health_record import HealthRecord
from app.models.user import User
from app.services import connection_sync_cli
from app.services.connection_query import create_connection
from app.services.connectors.base import NormalizedRecord, SourceConnector
from app.services.connectors.oura import OURA_SOURCE_NAME
from app.services.crypto import CredentialCipher

_KEY = Fernet.generate_key().decode()
_BEDTIME_END = dt.datetime(2026, 6, 10, 7, 30, tzinfo=dt.timezone.utc)


class _FakeConnector(SourceConnector):
    provider = ConnectionProvider.oura
    source_name = OURA_SOURCE_NAME

    async def pull(self, credential, since):
        return [
            NormalizedRecord(
                kind="metric", type="HeartRateVariabilitySDNN", value=60.0,
                unit="ms", time=_BEDTIME_END,
            ),
        ]


async def test_run_scheduled_sync_skips_without_a_key(db_session, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "CONNECTION_ENCRYPTION_KEY", None)
    # Even if a session were opened it would do nothing; assert it returns 0.
    synced = await connection_sync_cli.run_scheduled_sync()
    assert synced == 0


async def test_run_scheduled_sync_syncs_active_connections(db_session, monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "CONNECTION_ENCRYPTION_KEY", _KEY)

    alice = User(email="alice@example.com")
    db_session.add(alice)
    await db_session.flush()
    await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential="atok", cipher=CredentialCipher(keys=[_KEY]),
    )
    await db_session.commit()

    # Make the CLI use the test session (a no-op async context manager wrapper).
    @contextlib.asynccontextmanager
    async def _fake_session():
        yield db_session

    monkeypatch.setattr(connection_sync_cli, "async_session", _fake_session)
    # And a mocked connector factory (no network).
    monkeypatch.setattr(
        "app.services.connection_query.get_connector",
        lambda provider: _FakeConnector(),
    )

    synced = await connection_sync_cli.run_scheduled_sync()
    assert synced == 1

    count = (
        await db_session.execute(
            select(func.count()).select_from(HealthRecord).where(
                HealthRecord.user_id == alice.id
            )
        )
    ).scalar()
    assert count == 1
