"""Connection query/sync layer — DB glue for BYOT integrations (connections).

The DB-touching glue around the pure connector framework
(:mod:`app.services.connectors`), mirroring the
:mod:`app.services.off_lookup` / :mod:`app.services.fitbod_import` pattern. It
owns the four operations the API and the scheduler need:

* :func:`create_connection` — store (or replace) a user's **encrypted** credential
  for a provider. One row per (user, provider): re-connecting updates the row and
  resets it to ``active``. The credential is encrypted with
  :class:`~app.services.crypto.CredentialCipher` **before** insert — never
  plaintext.
* :func:`get_connection` / :func:`list_connections` — read a user's own
  Connection(s). Per-user scoped (a foreign Connection is invisible).
* :func:`disconnect_connection` — delete a user's own Connection (scoped).
* :func:`sync_connection` — pull on demand: decrypt the credential **in memory**,
  hand it to the provider's connector, normalise the result into
  ``health_records`` / ``category_records`` through the **existing idempotent
  dedup** (so a re-pull never duplicates — CONTEXT.md "Import"), attribute it to
  an Oura :class:`~app.models.data_source.DataSource` + an
  :class:`~app.models.import_batch.ImportBatch`, and update the Connection's
  ``status`` / ``last_sync_at`` / ``last_error``. A provider failure
  (:class:`~app.services.connectors.base.ConnectorError`) sets ``status=error``
  with a clear, **credential-free** message — it never crashes.
* :func:`sync_all_active` — what a K8s CronJob invokes per active Connection (the
  scheduled-puller kind from ADR-0006). Isolates failures per Connection.

The credential's plaintext lives only in this module's local variables during a
pull; it is never logged and never returned to a caller.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import (
    Connection,
    ConnectionProvider,
    ConnectionStatus,
)
from app.models.data_source import DataSource
from app.models.import_batch import ImportBatch
from app.models.user import User
from app.services.connectors import get_connector
from app.services.connectors.base import (
    ConnectorError,
    NormalizedRecord,
    SourceConnector,
)
from app.services.crypto import CredentialCipher
from app.services.dedup import (
    bulk_insert_category_records,
    bulk_insert_health_records,
)

log = logging.getLogger(__name__)


class ConnectionNotFound(LookupError):
    """The requested Connection doesn't exist for this user (404 / scoping)."""


@dataclass(frozen=True)
class SyncOutcome:
    """The result of a sync — what the API surfaces (never the credential)."""

    status: ConnectionStatus
    records_ingested: int
    last_sync_at: dt.datetime | None
    last_error: str | None


# --------------------------------------------------------------------------- #
# CRUD (per-user scoped)
# --------------------------------------------------------------------------- #


async def get_connection(
    db: AsyncSession, *, user: User, provider: ConnectionProvider
) -> Connection:
    """Return the user's own Connection for ``provider`` or raise ConnectionNotFound."""
    conn = (
        await db.execute(
            select(Connection).where(
                Connection.user_id == user.id, Connection.provider == provider
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise ConnectionNotFound(provider.value)
    return conn


async def list_connections(db: AsyncSession, *, user: User) -> list[Connection]:
    """All of the caller's own Connections (never another user's)."""
    rows = (
        await db.execute(
            select(Connection)
            .where(Connection.user_id == user.id)
            .order_by(Connection.provider)
        )
    ).scalars().all()
    return list(rows)


async def create_connection(
    db: AsyncSession,
    *,
    user: User,
    provider: ConnectionProvider,
    credential: str,
    cipher: CredentialCipher,
) -> Connection:
    """Store (or replace) the user's encrypted credential for ``provider``.

    One Connection per (user, provider): if one exists it is updated in place
    (credential replaced, status reset to ``active``, prior error cleared) so
    re-pasting a token never duplicates. The credential is encrypted before it
    touches the row.
    """
    ciphertext = cipher.encrypt(credential)
    existing = (
        await db.execute(
            select(Connection).where(
                Connection.user_id == user.id, Connection.provider == provider
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.encrypted_credential = ciphertext
        existing.status = ConnectionStatus.active
        existing.last_error = None
        return existing

    conn = Connection(
        user_id=user.id,
        provider=provider,
        encrypted_credential=ciphertext,
        status=ConnectionStatus.active,
    )
    db.add(conn)
    return conn


async def disconnect_connection(
    db: AsyncSession, *, user: User, provider: ConnectionProvider
) -> None:
    """Delete the user's own Connection for ``provider`` (scoped).

    Raises :class:`ConnectionNotFound` if the user has no such Connection — so a
    user can never delete another user's row by guessing a provider.
    """
    conn = await get_connection(db, user=user, provider=provider)
    await db.delete(conn)


# --------------------------------------------------------------------------- #
# Sync (on-demand + scheduled)
# --------------------------------------------------------------------------- #


async def _get_or_create_source(db: AsyncSession, name: str) -> DataSource:
    """Get-or-create the shared :class:`DataSource` for a provider (no bundle id)."""
    source = (
        await db.execute(
            select(DataSource).where(
                DataSource.name == name, DataSource.bundle_id.is_(None)
            )
        )
    ).scalar_one_or_none()
    if source is None:
        source = DataSource(name=name, bundle_id=None)
        db.add(source)
        await db.flush()
    return source


def _split_records(
    records: list[NormalizedRecord],
    *,
    user_id: int,
    source_id: int,
    batch_id,
) -> tuple[list[dict], list[dict]]:
    """Turn NormalizedRecords into health_records / category_records insert dicts.

    Columns match the dedup helpers' expectations exactly
    (:mod:`app.services.dedup`). Idempotency is the existing ON CONFLICT DO
    NOTHING on each table's natural key.
    """
    health: list[dict] = []
    category: list[dict] = []
    for r in records:
        if r.kind == "metric":
            health.append(
                {
                    "time": r.time,
                    "user_id": user_id,
                    "metric_type": r.type,
                    "value": r.value,
                    "unit": r.unit,
                    "end_time": r.end_time,
                    "source_id": source_id,
                    "batch_id": batch_id,
                }
            )
        else:  # category
            category.append(
                {
                    "time": r.time,
                    "user_id": user_id,
                    "category_type": r.type,
                    "value": r.category_value or r.value_label or "",
                    "value_label": r.value_label,
                    "end_time": r.end_time,
                    "source_id": source_id,
                    "batch_id": batch_id,
                }
            )
    return health, category


async def sync_connection(
    db: AsyncSession,
    *,
    connection: Connection,
    cipher: CredentialCipher,
    connector: SourceConnector | None = None,
    now: dt.datetime,
) -> SyncOutcome:
    """Pull a Connection's data and land it idempotently. Never raises on a provider error.

    Decrypts the credential in memory, asks the provider's connector to pull
    everything since the last successful sync (a full backfill on the first run),
    normalises the result into ``health_records`` / ``category_records`` via the
    idempotent dedup, and records an Oura Source + ImportBatch. Updates the
    Connection's ``status`` / ``last_sync_at`` / ``last_error`` and returns a
    :class:`SyncOutcome`. A :class:`ConnectorError` (auth or transient) is caught
    and turned into ``status=error`` with a clear, credential-free message.

    ``connector`` is injectable for tests; in production it's resolved from the
    registry by the Connection's provider. Flushes within the caller's
    transaction; the caller commits.
    """
    if connector is None:
        connector = get_connector(connection.provider)

    # Decrypt in memory only, never logged. `since` resumes from the last sync.
    credential = cipher.decrypt(connection.encrypted_credential)
    since = connection.last_sync_at

    try:
        records = await connector.pull(credential, since)
    except ConnectorError as exc:
        # A provider failure (invalid token / unreachable) — record a clear,
        # credential-free reason and keep the row. Never crash.
        connection.status = ConnectionStatus.error
        connection.last_error = str(exc)
        await db.flush()
        log.info(
            "Connection %s (%s) sync failed: %s",
            connection.id, connection.provider.value, type(exc).__name__,
        )
        return SyncOutcome(
            status=ConnectionStatus.error,
            records_ingested=0,
            last_sync_at=connection.last_sync_at,
            last_error=connection.last_error,
        )

    ingested = 0
    if records:
        source = await _get_or_create_source(db, connector.source_name)
        batch = ImportBatch(
            user_id=connection.user_id,
            filename=f"{connection.provider.value}-sync",
            status="completed",
            record_count=len(records),
            error_message=None,
        )
        db.add(batch)
        await db.flush()  # need batch.id + source.id for attribution

        health_rows, category_rows = _split_records(
            records,
            user_id=connection.user_id,
            source_id=source.id,
            batch_id=batch.id,
        )
        if health_rows:
            await bulk_insert_health_records(db, health_rows)
        if category_rows:
            await bulk_insert_category_records(db, category_rows)
        ingested = len(records)

    connection.status = ConnectionStatus.active
    connection.last_sync_at = now
    connection.last_error = None
    await db.flush()
    return SyncOutcome(
        status=ConnectionStatus.active,
        records_ingested=ingested,
        last_sync_at=now,
        last_error=None,
    )


async def sync_all_active(
    db: AsyncSession,
    *,
    cipher: CredentialCipher,
    connector_factory: Callable[[ConnectionProvider], SourceConnector] | None = None,
    now: dt.datetime,
) -> int:
    """Sync every ``active`` Connection — the scheduled-puller entrypoint.

    What a K8s CronJob invokes (via :mod:`app.services.connection_sync_cli`). Each
    Connection is synced independently; one failing (it ends up ``status=error``)
    never aborts the others. Returns the count that synced **successfully**.

    ``connector_factory`` maps a provider to its connector (injectable for tests);
    defaults to the registry.
    """
    factory = connector_factory or get_connector
    rows = (
        await db.execute(
            select(Connection).where(Connection.status == ConnectionStatus.active)
        )
    ).scalars().all()

    succeeded = 0
    for conn in rows:
        try:
            connector = factory(conn.provider)
            outcome = await sync_connection(
                db, connection=conn, cipher=cipher, connector=connector, now=now,
            )
            # Commit each Connection independently so one later failure can't roll
            # back an earlier success — the right durability for a batch job. (The
            # error-status write inside sync_connection is committed too.)
            await db.commit()
            if outcome.status is ConnectionStatus.active:
                succeeded += 1
        except Exception:  # noqa: BLE001 - one bad connection must not abort the run
            # An *unexpected* error (a bug, not a provider failure) — roll back the
            # poisoned transaction so the next Connection starts clean, and carry on.
            await db.rollback()
            log.exception(
                "Unexpected error syncing connection %s; continuing", conn.id
            )
    return succeeded
