"""Connection query/sync layer — DB glue for BYOT integrations (connections).

DB-backed (real Postgres via ``db_session``) but **never hits the network** — the
Oura HTTP call is mocked with an injected connector returning canned
NormalizedRecords, or an ``httpx.MockTransport`` for the real connector. Pins the
security-critical + idempotency contract from the acceptance criteria:

* **encryption at rest** — ``create_connection`` stores Fernet ciphertext; the
  plaintext token never appears in the stored row (asserted against every column);
* **sync lands the right Metric samples** — HRV → ``HeartRateVariabilitySDNN``,
  resting HR → ``RestingHeartRate``, sleep → a ``SleepAnalysis`` asleep interval —
  attributed to an Oura ``DataSource`` + an ``ImportBatch``, status → active,
  ``last_sync_at`` set;
* **idempotent re-pull** — syncing the same data twice inserts nothing the second
  time (the existing dedup);
* **invalid token → status=error**, ``last_error`` set, no crash, no records, and
  the error string never contains the token;
* **per-user scoping** — a user can't read/sync/disconnect another user's
  Connection.
"""

import datetime as dt

import httpx
import pytest
from sqlalchemy import func, select

from app.models.category_record import CategoryRecord
from app.models.connection import (
    Connection,
    ConnectionProvider,
    ConnectionStatus,
)
from app.models.data_source import DataSource
from app.models.health_record import HealthRecord
from app.models.import_batch import ImportBatch
from app.models.user import User
from app.services.connectors.base import (
    ConnectorAuthError,
    NormalizedRecord,
    SourceConnector,
)
from app.services.connectors.oura import OURA_SOURCE_NAME
from app.services.crypto import CredentialCipher
from app.services.connection_query import (
    ConnectionNotFound,
    create_connection,
    disconnect_connection,
    get_connection,
    list_connections,
    sync_all_active,
    sync_connection,
)

from cryptography.fernet import Fernet

_KEY = Fernet.generate_key().decode()
_TOKEN = "OURA-PAT-SECRET-7c3f9b2a1e4d8f6a0b5c2d1e"

_NOW = dt.datetime(2026, 6, 12, 12, 0, tzinfo=dt.timezone.utc)
_BEDTIME_END = dt.datetime(2026, 6, 10, 7, 30, tzinfo=dt.timezone.utc)


def _cipher() -> CredentialCipher:
    return CredentialCipher(keys=[_KEY])


async def _make_user(db, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


class _FakeConnector(SourceConnector):
    """A stand-in connector with no network — returns canned records or raises.

    Records the ``credential`` it was handed so a test can prove the *decrypted*
    token reaches the provider (and nothing else does).
    """

    provider = ConnectionProvider.oura
    source_name = OURA_SOURCE_NAME

    def __init__(self, records=None, *, error: Exception | None = None) -> None:
        self._records = records or []
        self._error = error
        self.calls: list[tuple[str, dt.datetime | None]] = []

    async def pull(self, credential, since):
        self.calls.append((credential, since))
        if self._error is not None:
            raise self._error
        return list(self._records)


def _recovery_records() -> list[NormalizedRecord]:
    """One night of HRV / resting HR / sleep, the shape OuraConnector emits."""
    return [
        NormalizedRecord(
            kind="metric", type="HeartRateVariabilitySDNN", value=65.0,
            unit="ms", time=_BEDTIME_END,
        ),
        NormalizedRecord(
            kind="metric", type="RestingHeartRate", value=48.0,
            unit="count/min", time=_BEDTIME_END,
        ),
        NormalizedRecord(
            kind="category", type="SleepAnalysis", unit="",
            time=_BEDTIME_END - dt.timedelta(seconds=27000),
            end_time=_BEDTIME_END,
            category_value="HKCategoryValueSleepAnalysisAsleep",
            value_label="Asleep",
        ),
    ]


# --------------------------------------------------------------------------- #
# Encryption at rest
# --------------------------------------------------------------------------- #


async def test_create_connection_stores_ciphertext_not_plaintext(db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    conn = await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential=_TOKEN, cipher=_cipher(),
    )
    await db_session.flush()

    # The stored credential is ciphertext — not the plaintext, in any column.
    assert conn.encrypted_credential != _TOKEN.encode()
    assert _TOKEN.encode() not in conn.encrypted_credential
    # And it decrypts back to the token (round-trip through the row).
    assert _cipher().decrypt(conn.encrypted_credential) == _TOKEN

    # The plaintext token appears in NONE of the row's string/bytes fields.
    row_blob = " ".join(
        str(getattr(conn, c.name)) for c in Connection.__table__.columns
        if c.name != "encrypted_credential"
    )
    assert _TOKEN not in row_blob


async def test_reconnect_replaces_credential_on_the_same_row(db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    first = await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential="old-token", cipher=_cipher(),
    )
    await db_session.flush()
    first_id = first.id

    # Re-connect with a new token — UNIQUE(user_id, provider) means update, not dup.
    second = await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential="new-token", cipher=_cipher(),
    )
    await db_session.flush()

    assert second.id == first_id  # same row
    assert _cipher().decrypt(second.encrypted_credential) == "new-token"
    count = (
        await db_session.execute(select(func.count()).select_from(Connection))
    ).scalar()
    assert count == 1


# --------------------------------------------------------------------------- #
# Sync — lands the right Metric samples, idempotently
# --------------------------------------------------------------------------- #


async def test_sync_lands_hrv_rhr_sleep_and_marks_active(db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    conn = await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential=_TOKEN, cipher=_cipher(),
    )
    await db_session.flush()

    connector = _FakeConnector(_recovery_records())
    result = await sync_connection(
        db_session, connection=conn, cipher=_cipher(), connector=connector, now=_NOW,
    )

    # The connector received the DECRYPTED token (proves decrypt-at-pull-time).
    assert connector.calls and connector.calls[0][0] == _TOKEN

    # HRV + RHR landed in health_records for Alice with the right types/values.
    hrv = (
        await db_session.execute(
            select(HealthRecord).where(
                HealthRecord.user_id == alice.id,
                HealthRecord.metric_type == "HeartRateVariabilitySDNN",
            )
        )
    ).scalars().all()
    assert [r.value for r in hrv] == [65.0]
    rhr = (
        await db_session.execute(
            select(HealthRecord).where(
                HealthRecord.user_id == alice.id,
                HealthRecord.metric_type == "RestingHeartRate",
            )
        )
    ).scalars().all()
    assert [r.value for r in rhr] == [48.0]

    # Sleep landed as a SleepAnalysis asleep interval in category_records.
    sleep = (
        await db_session.execute(
            select(CategoryRecord).where(
                CategoryRecord.user_id == alice.id,
                CategoryRecord.category_type == "SleepAnalysis",
            )
        )
    ).scalars().all()
    assert len(sleep) == 1
    assert "Asleep" in sleep[0].value
    assert sleep[0].end_time is not None

    # An Oura DataSource + an ImportBatch were registered, records attributed.
    source = (
        await db_session.execute(
            select(DataSource).where(DataSource.name == OURA_SOURCE_NAME)
        )
    ).scalar_one()
    assert hrv[0].source_id == source.id
    batch = (
        await db_session.execute(
            select(ImportBatch).where(ImportBatch.user_id == alice.id)
        )
    ).scalar_one()
    assert batch.status == "completed"
    assert batch.record_count == 3

    # Status flipped to active; last_sync_at set; no error.
    assert result.status is ConnectionStatus.active
    assert conn.status is ConnectionStatus.active
    assert conn.last_sync_at is not None
    assert conn.last_error is None


async def test_resync_is_idempotent_adds_nothing(db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    conn = await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential=_TOKEN, cipher=_cipher(),
    )
    await db_session.flush()

    connector = _FakeConnector(_recovery_records())
    await sync_connection(
        db_session, connection=conn, cipher=_cipher(), connector=connector, now=_NOW,
    )
    await db_session.flush()

    health_after_first = (
        await db_session.execute(select(func.count()).select_from(HealthRecord))
    ).scalar()
    cat_after_first = (
        await db_session.execute(select(func.count()).select_from(CategoryRecord))
    ).scalar()

    # Re-pull the SAME night — dedup means no new rows.
    await sync_connection(
        db_session, connection=conn, cipher=_cipher(), connector=connector, now=_NOW,
    )
    await db_session.flush()

    health_after_second = (
        await db_session.execute(select(func.count()).select_from(HealthRecord))
    ).scalar()
    cat_after_second = (
        await db_session.execute(select(func.count()).select_from(CategoryRecord))
    ).scalar()

    assert health_after_second == health_after_first == 2
    assert cat_after_second == cat_after_first == 1


# --------------------------------------------------------------------------- #
# Invalid token → status=error, no crash, no leak
# --------------------------------------------------------------------------- #


async def test_invalid_token_sets_status_error_and_does_not_crash(db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    conn = await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential=_TOKEN, cipher=_cipher(),
    )
    await db_session.flush()

    connector = _FakeConnector(error=ConnectorAuthError("token rejected"))
    # Must NOT raise — the sync swallows the provider error into status=error.
    result = await sync_connection(
        db_session, connection=conn, cipher=_cipher(), connector=connector, now=_NOW,
    )

    assert result.status is ConnectionStatus.error
    assert conn.status is ConnectionStatus.error
    assert conn.last_error  # a clear message was recorded
    # The error message NEVER contains the token.
    assert _TOKEN not in conn.last_error
    # No records were written.
    count = (
        await db_session.execute(select(func.count()).select_from(HealthRecord))
    ).scalar()
    assert count == 0


async def test_error_then_successful_resync_clears_the_error(db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    conn = await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential=_TOKEN, cipher=_cipher(),
    )
    await db_session.flush()

    await sync_connection(
        db_session, connection=conn, cipher=_cipher(),
        connector=_FakeConnector(error=ConnectorAuthError("nope")), now=_NOW,
    )
    assert conn.status is ConnectionStatus.error

    await sync_connection(
        db_session, connection=conn, cipher=_cipher(),
        connector=_FakeConnector(_recovery_records()), now=_NOW,
    )
    assert conn.status is ConnectionStatus.active
    assert conn.last_error is None


# --------------------------------------------------------------------------- #
# Per-user scoping
# --------------------------------------------------------------------------- #


async def test_get_connection_is_scoped_to_the_owner(db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential=_TOKEN, cipher=_cipher(),
    )
    await db_session.flush()

    # Alice sees hers.
    assert await get_connection(db_session, user=alice, provider=ConnectionProvider.oura)
    # Bob cannot read Alice's Connection.
    with pytest.raises(ConnectionNotFound):
        await get_connection(db_session, user=bob, provider=ConnectionProvider.oura)


async def test_list_connections_only_returns_own(db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential="a", cipher=_cipher(),
    )
    await create_connection(
        db_session, user=bob, provider=ConnectionProvider.oura,
        credential="b", cipher=_cipher(),
    )
    await db_session.flush()

    alice_conns = await list_connections(db_session, user=alice)
    assert len(alice_conns) == 1
    assert alice_conns[0].user_id == alice.id


async def test_disconnect_is_scoped_to_the_owner(db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential=_TOKEN, cipher=_cipher(),
    )
    await db_session.flush()

    # Bob cannot disconnect Alice's Connection.
    with pytest.raises(ConnectionNotFound):
        await disconnect_connection(db_session, user=bob, provider=ConnectionProvider.oura)
    # Alice's is still there.
    assert await get_connection(db_session, user=alice, provider=ConnectionProvider.oura)

    # Alice can disconnect her own.
    await disconnect_connection(db_session, user=alice, provider=ConnectionProvider.oura)
    await db_session.flush()
    count = (
        await db_session.execute(select(func.count()).select_from(Connection))
    ).scalar()
    assert count == 0


# --------------------------------------------------------------------------- #
# Scheduled pull
# --------------------------------------------------------------------------- #


async def test_sync_all_active_pulls_each_active_connection(db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential="atok", cipher=_cipher(),
    )
    bob_conn = await create_connection(
        db_session, user=bob, provider=ConnectionProvider.oura,
        credential="btok", cipher=_cipher(),
    )
    await db_session.flush()
    # Disable Bob's — the scheduler should skip it.
    bob_conn.status = ConnectionStatus.disabled
    await db_session.flush()

    # Inject a connector factory so no network is touched.
    factory = lambda provider: _FakeConnector(_recovery_records())  # noqa: E731
    synced = await sync_all_active(
        db_session, cipher=_cipher(), connector_factory=factory, now=_NOW,
    )

    assert synced == 1  # only Alice's active connection
    # Alice got records; Bob did not.
    alice_count = (
        await db_session.execute(
            select(func.count()).select_from(HealthRecord).where(
                HealthRecord.user_id == alice.id
            )
        )
    ).scalar()
    bob_count = (
        await db_session.execute(
            select(func.count()).select_from(HealthRecord).where(
                HealthRecord.user_id == bob.id
            )
        )
    ).scalar()
    assert alice_count == 2
    assert bob_count == 0


async def test_sync_all_active_isolates_a_failing_connection(db_session) -> None:
    """One Connection erroring doesn't abort the others (per-connection try)."""
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    await create_connection(
        db_session, user=alice, provider=ConnectionProvider.oura,
        credential="atok", cipher=_cipher(),
    )
    await create_connection(
        db_session, user=bob, provider=ConnectionProvider.oura,
        credential="btok", cipher=_cipher(),
    )
    await db_session.flush()

    def factory(provider):
        # Alice fails, Bob succeeds — keyed by call order via a mutable closure.
        factory.n += 1  # type: ignore[attr-defined]
        if factory.n == 1:
            return _FakeConnector(error=ConnectorAuthError("bad"))
        return _FakeConnector(_recovery_records())

    factory.n = 0  # type: ignore[attr-defined]

    synced = await sync_all_active(
        db_session, cipher=_cipher(), connector_factory=factory, now=_NOW,
    )
    # One succeeded; the run didn't blow up on the failure.
    assert synced == 1
