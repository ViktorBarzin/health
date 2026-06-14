"""Rollups stay fresh on ingest (ADR-0009): the post-batch recompute hooks.

After a batch writes ``health_records`` the touched ``(user, metric, day)`` buckets
must be recomputed so the rollup-backed read path is correct without a full
rebuild. This pins the two production write paths that land Metric samples:

* the Apple Health XML import pipeline's per-batch flush
  (:func:`app.services.xml_parser._flush_batch`), and
* the Connector sync (:func:`app.services.connection_query.sync_connection`).

(Fitbod import writes training_sets, not health_records, so it's out of scope.)
The recompute is targeted (only the batch's keys) and idempotent.
"""

from __future__ import annotations

import datetime as dt
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.connection import Connection, ConnectionProvider, ConnectionStatus
from app.models.health_record import HealthRecord
from app.models.metric_daily import MetricDaily
from app.models.user import User
from app.services.connectors.base import NormalizedRecord, SourceConnector
from app.services.crypto import CredentialCipher
from app.services.connection_query import create_connection, sync_connection
from app.services.xml_parser import BatchPayload, _flush_batch

from cryptography.fernet import Fernet


async def _user(db, email: str = "alice@example.com") -> User:
    u = User(email=email)
    db.add(u)
    await db.flush()
    return u


# --------------------------------------------------------------------------- #
# XML import pipeline: _flush_batch refreshes rollups for the batch's keys
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_xml_flush_batch_refreshes_rollups(db_session) -> None:
    db = db_session
    user = await _user(db)
    await db.commit()

    # _flush_batch opens its own sessions from a factory and commits per table.
    # Bind a factory to the same engine the test session uses.
    factory = async_sessionmaker(bind=db.bind, expire_on_commit=False)

    day = datetime(2024, 1, 1, 8, 0, tzinfo=timezone.utc)
    batch = BatchPayload(
        health=[
            {"time": day, "user_id": user.id, "metric_type": "HeartRate", "value": 60.0, "unit": "count/min", "end_time": None, "source_id": None, "batch_id": None},
            {"time": day + timedelta(hours=1), "user_id": user.id, "metric_type": "HeartRate", "value": 80.0, "unit": "count/min", "end_time": None, "source_id": None, "batch_id": None},
            {"time": day, "user_id": user.id, "metric_type": "StepCount", "value": 500.0, "unit": "count", "end_time": None, "source_id": None, "batch_id": None},
        ]
    )

    await _flush_batch(factory, batch)

    rows = {
        (r.metric_type, r.day): r
        for r in (await db.execute(select(MetricDaily))).scalars().all()
    }
    assert rows[("HeartRate", day.date())].count == 2
    assert rows[("HeartRate", day.date())].sum == 140.0
    assert rows[("StepCount", day.date())].sum == 500.0


@pytest.mark.asyncio
async def test_xml_flush_batch_accumulates_across_batches(db_session) -> None:
    """A second batch landing more rows for the same day re-derives the bucket
    from ALL raw rows (not the in-batch subset)."""
    db = db_session
    user = await _user(db)
    await db.commit()
    factory = async_sessionmaker(bind=db.bind, expire_on_commit=False)
    day = datetime(2024, 2, 1, 8, 0, tzinfo=timezone.utc)

    await _flush_batch(factory, BatchPayload(health=[
        {"time": day, "user_id": user.id, "metric_type": "HeartRate", "value": 60.0, "unit": "u", "end_time": None, "source_id": None, "batch_id": None},
    ]))
    await _flush_batch(factory, BatchPayload(health=[
        {"time": day + timedelta(hours=2), "user_id": user.id, "metric_type": "HeartRate", "value": 100.0, "unit": "u", "end_time": None, "source_id": None, "batch_id": None},
    ]))

    row = (await db.execute(select(MetricDaily))).scalar_one()
    assert row.count == 2
    assert row.sum == 160.0
    assert row.min == 60.0
    assert row.max == 100.0


@pytest.mark.asyncio
async def test_xml_flush_batch_no_health_rows_is_noop(db_session) -> None:
    """A batch with only category/activity rows must not error or create rollups."""
    db = db_session
    user = await _user(db)
    await db.commit()
    factory = async_sessionmaker(bind=db.bind, expire_on_commit=False)
    day = datetime(2024, 1, 1, 23, 0, tzinfo=timezone.utc)
    batch = BatchPayload(category=[
        {"time": day, "user_id": user.id, "category_type": "SleepAnalysis", "value": "HKx", "value_label": "Asleep", "end_time": day + timedelta(hours=7), "source_id": None, "batch_id": None},
    ])
    await _flush_batch(factory, batch)
    rows = (await db.execute(select(MetricDaily))).scalars().all()
    assert rows == []


# --------------------------------------------------------------------------- #
# Connector sync refreshes rollups for the pulled Metric samples
# --------------------------------------------------------------------------- #


_KEY = Fernet.generate_key().decode()
_NOW = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)


class _FakeConnector(SourceConnector):
    provider = ConnectionProvider.oura
    source_name = "Oura"

    def __init__(self, records: list[NormalizedRecord]) -> None:
        self._records = records

    async def pull(self, credential: str, since):  # noqa: ANN001
        return self._records


@pytest.mark.asyncio
async def test_connector_sync_refreshes_rollups(db_session) -> None:
    db = db_session
    user = await _user(db)
    cipher = CredentialCipher(keys=[_KEY])
    conn = await create_connection(
        db, user=user, provider=ConnectionProvider.oura, credential="tok", cipher=cipher
    )
    await db.flush()

    night = datetime(2026, 6, 10, 7, 30, tzinfo=timezone.utc)
    records = [
        NormalizedRecord(kind="metric", type="HeartRateVariabilitySDNN", time=night, value=55.0, unit="ms", end_time=None),
        NormalizedRecord(kind="metric", type="RestingHeartRate", time=night, value=48.0, unit="count/min", end_time=None),
    ]
    outcome = await sync_connection(
        db, connection=conn, cipher=cipher, connector=_FakeConnector(records), now=_NOW
    )
    await db.commit()
    assert outcome.status is ConnectionStatus.active

    rows = {
        r.metric_type: r
        for r in (await db.execute(select(MetricDaily))).scalars().all()
    }
    assert rows["HeartRateVariabilitySDNN"].sum == 55.0
    assert rows["HeartRateVariabilitySDNN"].count == 1
    assert rows["RestingHeartRate"].sum == 48.0


@pytest.mark.asyncio
async def test_connector_sync_idempotent_rollup(db_session) -> None:
    """A re-pull (the existing ON CONFLICT dedup) leaves the rollup unchanged."""
    db = db_session
    user = await _user(db)
    cipher = CredentialCipher(keys=[_KEY])
    conn = await create_connection(
        db, user=user, provider=ConnectionProvider.oura, credential="tok", cipher=cipher
    )
    await db.flush()
    night = datetime(2026, 6, 10, 7, 30, tzinfo=timezone.utc)
    records = [
        NormalizedRecord(kind="metric", type="HeartRateVariabilitySDNN", time=night, value=55.0, unit="ms", end_time=None),
    ]
    await sync_connection(db, connection=conn, cipher=cipher, connector=_FakeConnector(records), now=_NOW)
    await db.commit()
    # second identical pull
    await sync_connection(db, connection=conn, cipher=cipher, connector=_FakeConnector(records), now=_NOW)
    await db.commit()

    row = (await db.execute(select(MetricDaily))).scalar_one()
    assert row.count == 1
    assert row.sum == 55.0
