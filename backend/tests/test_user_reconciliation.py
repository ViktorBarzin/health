"""Reconciliation of the 3 existing prod users to their Authentik identities
(ADR-0003 / migration ``b8c2d4e6f0a1``).

Two operations, both idempotent and safe to run on any database (they act only
on rows that exist):

1. RENAME  ancaelena98@yahoo.com -> ancaelena98@gmail.com (Anca's Authentik email)
2. MERGE   me@viktorbarzin.me INTO vbarzin@gmail.com (Viktor's Authentik email):
   reassign every row the me@ user owns to the vbarzin@ user, then delete the
   now-empty me@ user. Where the target already owns the same-keyed row, prefer
   the existing row and drop the me@ duplicate (no constraint violation).

The tests drive ``reconcile_identities(connection)`` — the exact function the
migration's ``upgrade()`` calls — against a real Postgres with the full schema.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import text

from app.migrations_support.user_reconciliation import (
    ANCA_NEW,
    ANCA_OLD,
    VIKTOR_NEW,
    VIKTOR_OLD,
    reconcile_identities,
)


def _create_schema(conn) -> None:
    from app.database import Base

    Base.metadata.create_all(conn)


def _insert_user(conn, email: str) -> int:
    return conn.execute(
        text("INSERT INTO users (email) VALUES (:e) RETURNING id"), {"e": email}
    ).scalar_one()


def _user_id(conn, email: str) -> int | None:
    return conn.execute(
        text("SELECT id FROM users WHERE email = :e"), {"e": email}
    ).scalar_one_or_none()


def _insert_workout(conn, user_id: int, when: datetime, activity: str) -> uuid.UUID:
    wid = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO workouts (id, user_id, time, activity_type) "
            "VALUES (:id, :uid, :t, :a)"
        ),
        {"id": wid, "uid": user_id, "t": when, "a": activity},
    )
    return wid


def _insert_health_record(conn, user_id: int, when: datetime, metric: str, value: float) -> None:
    conn.execute(
        text(
            "INSERT INTO health_records (time, user_id, metric_type, value, unit) "
            "VALUES (:t, :uid, :m, :v, :u)"
        ),
        {"t": when, "uid": user_id, "m": metric, "v": value, "u": "count"},
    )


def _insert_route_point(conn, workout_id: uuid.UUID, when: datetime) -> None:
    conn.execute(
        text(
            "INSERT INTO workout_route_points (time, workout_id, latitude, longitude) "
            "VALUES (:t, :wid, :lat, :lon)"
        ),
        {"t": when, "wid": workout_id, "lat": 51.5, "lon": -0.12},
    )


def _count(conn, table: str, user_id: int) -> int:
    return conn.execute(
        text(f"SELECT count(*) FROM {table} WHERE user_id = :uid"), {"uid": user_id}
    ).scalar_one()


def test_renames_anca_yahoo_to_gmail(sync_engine) -> None:
    with sync_engine.begin() as conn:
        _create_schema(conn)
        _insert_user(conn, ANCA_OLD)

        reconcile_identities(conn)

        assert _user_id(conn, ANCA_OLD) is None
        assert _user_id(conn, ANCA_NEW) is not None


def test_anca_rename_skipped_when_already_on_new_email(sync_engine) -> None:
    with sync_engine.begin() as conn:
        _create_schema(conn)
        existing = _insert_user(conn, ANCA_NEW)

        reconcile_identities(conn)

        # Untouched: the already-correct row keeps its id, no duplicate created.
        assert _user_id(conn, ANCA_NEW) == existing


def test_anca_rename_prefers_existing_target_and_drops_duplicate(sync_engine) -> None:
    """If both yahoo and gmail rows exist, the gmail row wins and yahoo is
    reassigned into it, then removed — no unique-email violation."""
    with sync_engine.begin() as conn:
        _create_schema(conn)
        gmail_id = _insert_user(conn, ANCA_NEW)
        yahoo_id = _insert_user(conn, ANCA_OLD)
        t = datetime(2024, 1, 1, 10, tzinfo=timezone.utc)
        _insert_workout(conn, yahoo_id, t, "Running")

        reconcile_identities(conn)

        assert _user_id(conn, ANCA_OLD) is None
        assert _user_id(conn, ANCA_NEW) == gmail_id
        # The yahoo row's workout was reassigned to the surviving gmail user.
        assert _count(conn, "workouts", gmail_id) == 1


def test_merges_viktor_me_into_gmail_reassigning_rows(sync_engine) -> None:
    with sync_engine.begin() as conn:
        _create_schema(conn)
        gmail_id = _insert_user(conn, VIKTOR_NEW)
        me_id = _insert_user(conn, VIKTOR_OLD)
        t1 = datetime(2024, 1, 1, 10, tzinfo=timezone.utc)
        t2 = datetime(2024, 1, 2, 10, tzinfo=timezone.utc)
        _insert_workout(conn, me_id, t1, "Running")
        _insert_health_record(conn, me_id, t2, "HeartRate", 60.0)

        reconcile_identities(conn)

        # me@ user is gone; its rows now belong to the gmail user.
        assert _user_id(conn, VIKTOR_OLD) is None
        assert _user_id(conn, VIKTOR_NEW) == gmail_id
        assert _count(conn, "workouts", gmail_id) == 1
        assert _count(conn, "health_records", gmail_id) == 1


def test_viktor_merge_handles_colliding_composite_pk(sync_engine) -> None:
    """A health_records row with the SAME (time, metric_type) under both users:
    the target's row is preferred and the me@ duplicate is dropped without
    violating the composite primary key."""
    with sync_engine.begin() as conn:
        _create_schema(conn)
        gmail_id = _insert_user(conn, VIKTOR_NEW)
        me_id = _insert_user(conn, VIKTOR_OLD)
        t = datetime(2024, 1, 1, 10, tzinfo=timezone.utc)
        # Same (time, metric_type) for both users -> PK collision on reassign.
        _insert_health_record(conn, gmail_id, t, "HeartRate", 60.0)
        _insert_health_record(conn, me_id, t, "HeartRate", 99.0)
        # A non-colliding row that MUST be carried over.
        _insert_health_record(conn, me_id, t, "StepCount", 1000.0)

        reconcile_identities(conn)

        assert _user_id(conn, VIKTOR_OLD) is None
        # HeartRate: existing gmail row preferred (value 60), me dup dropped.
        hr = conn.execute(
            text(
                "SELECT value FROM health_records "
                "WHERE user_id = :uid AND metric_type = 'HeartRate'"
            ),
            {"uid": gmail_id},
        ).scalar_one()
        assert hr == 60.0
        # StepCount: carried over.
        assert _count(conn, "health_records", gmail_id) == 2


def test_viktor_merge_handles_colliding_workout_unique(sync_engine) -> None:
    """workouts has UNIQUE(user_id, time, activity_type); a duplicate under both
    users must not break the merge."""
    with sync_engine.begin() as conn:
        _create_schema(conn)
        gmail_id = _insert_user(conn, VIKTOR_NEW)
        me_id = _insert_user(conn, VIKTOR_OLD)
        t = datetime(2024, 1, 1, 10, tzinfo=timezone.utc)
        _insert_workout(conn, gmail_id, t, "Running")
        _insert_workout(conn, me_id, t, "Running")  # collides on unique constraint
        _insert_workout(conn, me_id, t, "Cycling")  # unique -> carried over

        reconcile_identities(conn)

        assert _user_id(conn, VIKTOR_OLD) is None
        assert _count(conn, "workouts", gmail_id) == 2  # Running (kept) + Cycling


def test_viktor_merge_drops_route_points_of_colliding_workout(sync_engine) -> None:
    """A colliding me@ workout that has GPS route points must not abort the
    merge: workout_route_points.workout_id -> workouts.id is a plain FK (no ON
    DELETE CASCADE), so the dropped duplicate's route points are removed first.

    Reachable on real prod data — me@viktorbarzin.me and vbarzin@gmail.com are
    both Viktor's accounts, so the same outdoor (GPS) workouts were plausibly
    imported under both. The surviving (target) workout and its data stay intact.
    """
    with sync_engine.begin() as conn:
        _create_schema(conn)
        gmail_id = _insert_user(conn, VIKTOR_NEW)
        me_id = _insert_user(conn, VIKTOR_OLD)
        t = datetime(2024, 1, 1, 10, tzinfo=timezone.utc)

        # Surviving target workout, with its own route point that must remain.
        kept = _insert_workout(conn, gmail_id, t, "Running")
        _insert_route_point(conn, kept, t)
        # Colliding me@ duplicate carrying a route point (the FK-violation trigger).
        dup = _insert_workout(conn, me_id, t, "Running")
        _insert_route_point(conn, dup, t)
        # A non-colliding me@ workout WITH a route point — both must carry over,
        # the workout's UUID is unchanged so its points follow automatically.
        carried = _insert_workout(conn, me_id, t, "Cycling")
        _insert_route_point(conn, carried, t)

        reconcile_identities(conn)

        assert _user_id(conn, VIKTOR_OLD) is None
        assert _count(conn, "workouts", gmail_id) == 2  # Running (kept) + Cycling
        # The dropped duplicate's route point is gone; the kept + carried ones
        # remain (2 total), still pointing at existing workouts.
        total_points = conn.execute(
            text("SELECT count(*) FROM workout_route_points")
        ).scalar_one()
        assert total_points == 2
        assert conn.execute(
            text("SELECT count(*) FROM workout_route_points WHERE workout_id = :wid"),
            {"wid": dup},
        ).scalar_one() == 0
        assert conn.execute(
            text("SELECT count(*) FROM workout_route_points WHERE workout_id = :wid"),
            {"wid": carried},
        ).scalar_one() == 1


def test_idempotent_second_run_is_a_noop(sync_engine) -> None:
    with sync_engine.begin() as conn:
        _create_schema(conn)
        _insert_user(conn, ANCA_OLD)
        gmail_id = _insert_user(conn, VIKTOR_NEW)
        me_id = _insert_user(conn, VIKTOR_OLD)
        t = datetime(2024, 1, 1, 10, tzinfo=timezone.utc)
        _insert_workout(conn, me_id, t, "Running")

        reconcile_identities(conn)
        anca_id_after_first = _user_id(conn, ANCA_NEW)
        # Running it again must change nothing.
        reconcile_identities(conn)

        assert _user_id(conn, ANCA_NEW) == anca_id_after_first
        assert _user_id(conn, ANCA_OLD) is None
        assert _user_id(conn, VIKTOR_OLD) is None
        assert _user_id(conn, VIKTOR_NEW) == gmail_id
        assert _count(conn, "workouts", gmail_id) == 1


def test_runs_clean_on_empty_database(sync_engine) -> None:
    """Safe to run anywhere: no target rows present -> no error, no rows made."""
    with sync_engine.begin() as conn:
        _create_schema(conn)

        reconcile_identities(conn)

        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 0
