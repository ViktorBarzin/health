"""Push-ingest DB glue (M7, ADR-0012): tokens + landing the parsed payload.

Tokens: SHA-256 of a ``hlth_``-prefixed 32-byte urlsafe secret; plaintext
returned exactly once. Landing mirrors the Connector sync
(:mod:`app.services.connection_query`): the same idempotent bulk inserts, the
same targeted rollup recompute, an ``Apple Shortcut`` DataSource and an
ImportBatch per POST — a re-send changes nothing.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_source import DataSource
from app.models.import_batch import ImportBatch
from app.models.ingest_token import IngestToken
from app.models.workout import Workout
from app.services import rollup
from app.services.dedup import (
    bulk_insert_category_records,
    bulk_insert_health_records,
)
from app.services.ingest import ParsedPayload

_TOKEN_PREFIX = "hlth_"
_KCAL_TO_KJ = 4.184

#: The Source name every Shortcut-pushed record is attributed to.
SOURCE_NAME = "Apple Shortcut"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_token(db: AsyncSession, user_id: int, *, label: str) -> tuple[IngestToken, str]:
    """Mint a token; returns (row, PLAINTEXT) — the only time plaintext exists."""
    plaintext = _TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = IngestToken(
        user_id=user_id,
        label=label,
        token_hash=_hash(plaintext),
        prefix=plaintext[:10],
    )
    db.add(row)
    await db.flush()
    return row, plaintext


async def list_tokens(db: AsyncSession, user_id: int) -> list[IngestToken]:
    rows = (
        await db.execute(
            select(IngestToken)
            .where(IngestToken.user_id == user_id)
            .order_by(IngestToken.created_at)
        )
    ).scalars()
    return list(rows)


async def revoke_token(db: AsyncSession, user_id: int, token_id: uuid.UUID) -> bool:
    row = (
        await db.execute(
            select(IngestToken).where(
                IngestToken.id == token_id, IngestToken.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


async def resolve_token(
    db: AsyncSession, plaintext: str, *, now: dt.datetime
) -> int | None:
    """The bearer check: plaintext → user id (and last-used bookkeeping)."""
    if not plaintext or not plaintext.startswith(_TOKEN_PREFIX):
        return None
    row = (
        await db.execute(
            select(IngestToken).where(IngestToken.token_hash == _hash(plaintext))
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    row.last_used_at = now
    await db.flush()
    return row.user_id


async def _get_or_create_source(db: AsyncSession) -> DataSource:
    source = (
        await db.execute(
            select(DataSource).where(
                DataSource.name == SOURCE_NAME, DataSource.bundle_id.is_(None)
            )
        )
    ).scalar_one_or_none()
    if source is None:
        source = DataSource(name=SOURCE_NAME, bundle_id=None)
        db.add(source)
        await db.flush()
    return source


async def land_payload(
    db: AsyncSession, user_id: int, payload: ParsedPayload
) -> dict[str, int]:
    """Land a parsed push idempotently; returns the accepted counts."""
    source = await _get_or_create_source(db)
    batch = ImportBatch(
        user_id=user_id,
        filename=f"apple-shortcut-{dt.datetime.now(dt.timezone.utc).isoformat()}",
        status="completed",
        record_count=len(payload.metrics) + len(payload.sleep) + len(payload.workouts),
        error_message=None,
    )
    db.add(batch)
    await db.flush()

    health_rows = [
        {
            "time": m.time,
            "user_id": user_id,
            "metric_type": m.type,
            "value": m.value,
            "unit": m.unit,
            "end_time": None,
            "source_id": source.id,
            "batch_id": batch.id,
        }
        for m in payload.metrics
    ]
    if health_rows:
        await bulk_insert_health_records(db, health_rows)
        # Same-transaction targeted rollup recompute (ADR-0009) — idempotent
        # like the dedup, so a re-send recomputes identical buckets.
        await rollup.recompute_for_rows(db, health_rows)

    category_rows = [
        {
            "time": s.start,
            "user_id": user_id,
            "category_type": "SleepAnalysis",
            "value": s.category_value,
            "value_label": s.label,
            "end_time": s.end,
            "source_id": source.id,
            "batch_id": batch.id,
        }
        for s in payload.sleep
    ]
    if category_rows:
        await bulk_insert_category_records(db, category_rows)

    for w in payload.workouts:
        stmt = (
            pg_insert(Workout)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                time=w.start,
                end_time=w.end,
                activity_type=w.type,
                duration_sec=(w.end - w.start).total_seconds(),
                total_distance_m=(w.distance_km * 1000.0) if w.distance_km else None,
                total_energy_kj=(w.energy_kcal * _KCAL_TO_KJ) if w.energy_kcal else None,
                source_id=source.id,
                batch_id=batch.id,
            )
            .on_conflict_do_nothing(
                index_elements=["user_id", "time", "activity_type"]
            )
        )
        await db.execute(stmt)
    await db.flush()

    return {
        "metrics": len(payload.metrics),
        "sleep": len(payload.sleep),
        "workouts": len(payload.workouts),
        "skipped": payload.skipped,
    }
