"""Idempotent reconciliation of the existing prod users to Authentik identities.

Used by the Alembic data migration (``b8c2d4e6f0a1``) and exercised directly by
tests. Pure SQLAlchemy Core against a sync ``Connection`` so it runs inside an
Alembic migration unchanged.

Two operations, both safe to run on any database (they act only on rows that
exist, and re-running them is a no-op):

1. RENAME ``ancaelena98@yahoo.com`` -> ``ancaelena98@gmail.com``.
2. MERGE ``me@viktorbarzin.me`` INTO ``vbarzin@gmail.com``: reassign every row
   the me@ user owns to the vbarzin@ user, then delete the now-empty me@ user.

Both are a single primitive — :func:`_merge_user(source, target)`:
- source absent          -> no-op
- target absent          -> rename source's email to target (a pure relabel)
- both present           -> reassign source's owned rows into target (dropping
                            rows that would collide with one the target already
                            owns — prefer existing), then delete the source user.

A dropped colliding ``workouts`` row first has its ``workout_route_points``
deleted, since that child FK has no ON DELETE CASCADE; the duplicate's GPS trace
is discarded with it. Reassigned (non-colliding) workouts keep their UUID, so
their route points follow them untouched.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

# Identities are fixed facts (verified 2026-06-05): Viktor's Authentik login is
# vbarzin@gmail.com (me@viktorbarzin.me is retired); Anca's is her gmail.
ANCA_OLD = "ancaelena98@yahoo.com"
ANCA_NEW = "ancaelena98@gmail.com"
VIKTOR_OLD = "me@viktorbarzin.me"
VIKTOR_NEW = "vbarzin@gmail.com"

# Every table owning rows via ``user_id`` -> the columns of its NARROWEST
# per-user uniqueness constraint, EXCLUDING user_id. Two rows sharing these
# columns collide once both belong to the same user, so the source row must be
# dropped rather than reassigned. ``import_batches`` has no per-user constraint
# (PK is its own UUID), so all its rows reassign freely.
#
# health_records also has UNIQUE(user_id, metric_type, time, value, source_id),
# but that key is a superset of the PK key (time, metric_type) — any collision
# on it implies a PK collision — so the PK key alone is sufficient.
_USER_OWNED_TABLES: dict[str, tuple[str, ...]] = {
    "health_records": ("time", "metric_type"),
    "category_records": ("time", "category_type"),
    "activity_summaries": ("date",),
    "workouts": ("time", "activity_type"),
    "import_batches": (),
}


def reconcile_identities(conn: Connection) -> None:
    """Apply both reconciliations. Idempotent; safe on any database."""
    _merge_user(conn, source_email=ANCA_OLD, target_email=ANCA_NEW)
    _merge_user(conn, source_email=VIKTOR_OLD, target_email=VIKTOR_NEW)


def _user_id(conn: Connection, email: str) -> int | None:
    return conn.execute(
        text("SELECT id FROM users WHERE email = :email"), {"email": email}
    ).scalar_one_or_none()


def _merge_user(conn: Connection, *, source_email: str, target_email: str) -> None:
    source_id = _user_id(conn, source_email)
    if source_id is None:
        # Nothing to do — source identity not present on this database.
        return

    target_id = _user_id(conn, target_email)
    if target_id is None:
        # Target absent: a pure relabel. No rows move; the unique email travels
        # with the row.
        conn.execute(
            text("UPDATE users SET email = :target WHERE id = :sid"),
            {"target": target_email, "sid": source_id},
        )
        return

    if target_id == source_id:  # pragma: no cover - emails are distinct here
        return

    # Both exist: fold the source's owned rows into the target, then delete the
    # source user.
    for table, key_cols in _USER_OWNED_TABLES.items():
        _reassign_table(conn, table, key_cols, source_id=source_id, target_id=target_id)

    conn.execute(text("DELETE FROM users WHERE id = :sid"), {"sid": source_id})


def _reassign_table(
    conn: Connection,
    table: str,
    key_cols: tuple[str, ...],
    *,
    source_id: int,
    target_id: int,
) -> None:
    """Move ``table`` rows from source to target, dropping would-be duplicates.

    ``key_cols`` are the per-user uniqueness columns (excluding user_id). Source
    rows whose key already exists under the target are deleted (prefer the
    existing target row); the rest are reassigned. With no key columns every row
    reassigns. Quoting via SQLAlchemy's identifier preparer keeps reserved words
    like ``time`` / ``date`` safe.
    """
    prep = conn.dialect.identifier_preparer
    tbl = prep.quote(table)

    if key_cols:
        cols = ", ".join(prep.quote(c) for c in key_cols)
        # The colliding source rows about to be dropped (the target already owns
        # a row with the same per-user key).
        colliding = (
            f"SELECT * FROM {tbl} src "  # noqa: S608 - identifiers quoted, ids bound
            f"WHERE src.user_id = :source_id "
            f"AND ({cols}) IN ("
            f"  SELECT {cols} FROM {tbl} tgt WHERE tgt.user_id = :target_id"
            f")"
        )
        params = {"source_id": source_id, "target_id": target_id}

        # workouts.id is referenced by workout_route_points with a plain FK (no
        # ON DELETE CASCADE), so a dropped workout that has route points would
        # raise a ForeignKeyViolation. Remove those child rows first — the
        # discarded duplicate's GPS trace goes with it (consistent with "prefer
        # the existing target"). Non-colliding workouts keep their UUID, so their
        # route points follow the reassignment untouched.
        if table == "workouts":
            conn.execute(
                text(
                    "DELETE FROM workout_route_points "  # noqa: S608 - ids bound
                    "WHERE workout_id IN (SELECT id FROM (" + colliding + ") c)"
                ),
                params,
            )

        conn.execute(
            text(
                f"DELETE FROM {tbl} src "  # noqa: S608 - identifiers quoted, ids bound
                f"WHERE src.user_id = :source_id "
                f"AND ({cols}) IN ("
                f"  SELECT {cols} FROM {tbl} tgt WHERE tgt.user_id = :target_id"
                f")"
            ),
            params,
        )

    conn.execute(
        text(  # noqa: S608 - table identifier is quoted; ids are bound params
            f"UPDATE {tbl} SET user_id = :target_id WHERE user_id = :source_id"
        ),
        {"source_id": source_id, "target_id": target_id},
    )
