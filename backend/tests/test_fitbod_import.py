"""Fitbod import DB glue: write Sessions/Sets, idempotency, Source, PRs.

DB-backed (real Postgres via the ``db_session`` fixture). Covers the write path
(:mod:`app.services.fitbod_import`): parsed Sessions become ``training_sessions``
with ``started_at`` from the Fitbod date, Sets carry ``weight_kg``/``reps``/
``order_index``/``set_type``, warmups map to ``warmup``, the data is attributed
to the importing user + a Fitbod Source, PRs are reconciled, and re-importing the
same CSV adds nothing (idempotent).
"""

import uuid

import pytest

from app.models.data_source import DataSource
from app.models.exercise import Exercise
from app.models.personal_record import PersonalRecord
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.models.user import User
from app.services.fitbod_import import (
    FITBOD_SOURCE_NAME,
    commit_fitbod_import,
    preview_fitbod_import,
)
from sqlalchemy import func, select

HEADER = (
    "Date,Exercise,Reps,Weight(kg),Duration(s),Distance(m),"
    "Incline,Resistance,isWarmup,Note,multiplier"
)


def _csv(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


async def _make_user(db, email: str = "lifter@example.com") -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


async def _make_exercise(db, name: str, *, user_id=None) -> Exercise:
    ex = Exercise(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        user_id=user_id,
        source="free-exercise-db" if user_id is None else "custom",
    )
    db.add(ex)
    await db.flush()
    return ex


# --------------------------------------------------------------------------- #
# Preview (parse + match, no writes)
# --------------------------------------------------------------------------- #


async def test_preview_resolves_known_and_flags_unknown(db_session) -> None:
    user = await _make_user(db_session)
    await _make_exercise(db_session, "Barbell Squat")
    await _make_exercise(db_session, "Barbell Bench Press - Medium Grip")

    text = _csv(
        "2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0",
        "2021-12-27 10:00:00 +0000,Bench Press,8,80.0,0,0,0,0,false,,1.0",
        "2021-12-27 10:00:00 +0000,Mystery Machine,10,50.0,0,0,0,0,false,,1.0",
    )
    preview = await preview_fitbod_import(db_session, user=user, csv_text=text)

    assert preview.session_count == 1
    assert preview.set_count == 3
    # Back Squat (alias) + Bench Press (alias) resolved; Mystery Machine not.
    assert preview.matched_count == 2
    assert preview.unresolved_names == ["Mystery Machine"]


async def test_preview_does_not_write_anything(db_session) -> None:
    user = await _make_user(db_session)
    await _make_exercise(db_session, "Barbell Squat")
    text = _csv("2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0")

    await preview_fitbod_import(db_session, user=user, csv_text=text)

    assert (await db_session.execute(select(func.count(TrainingSession.id)))).scalar() == 0
    assert (await db_session.execute(select(func.count(TrainingSet.id)))).scalar() == 0


async def test_preview_reports_skipped_cardio_rows(db_session) -> None:
    user = await _make_user(db_session)
    await _make_exercise(db_session, "Barbell Squat")
    text = _csv(
        "2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0",
        "2021-12-27 10:30:00 +0000,Running,0,0.0,1800.0,5000.0,0,0,false,,1.0",
    )
    preview = await preview_fitbod_import(db_session, user=user, csv_text=text)
    assert preview.skipped_rows == 1


# --------------------------------------------------------------------------- #
# Commit (idempotent write)
# --------------------------------------------------------------------------- #


async def test_commit_creates_sessions_and_sets(db_session) -> None:
    user = await _make_user(db_session)
    squat = await _make_exercise(db_session, "Barbell Squat")

    text = _csv(
        "2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,true,,1.0",
        "2021-12-27 10:00:00 +0000,Back Squat,5,102.5,0,0,0,0,false,,1.0",
    )
    result = await commit_fitbod_import(
        db_session, user=user, csv_text=text, filename="fitbod.csv"
    )
    await db_session.commit()

    assert result.sessions_created == 1
    assert result.sets_created == 2

    sessions = (
        await db_session.execute(select(TrainingSession))
    ).scalars().all()
    assert len(sessions) == 1
    session = sessions[0]
    assert session.user_id == user.id
    # started_at preserves the Fitbod performed date.
    assert session.started_at.year == 2021
    assert session.started_at.month == 12
    assert session.started_at.day == 27

    sets = sorted(session.sets, key=lambda s: s.order_index)
    assert len(sets) == 2
    assert sets[0].set_type == SetType.warmup  # isWarmup=true
    assert sets[1].set_type == SetType.normal
    assert sets[0].weight_kg == 100.0
    assert sets[1].weight_kg == 102.5
    assert sets[0].exercise_id == squat.id
    assert [s.order_index for s in sets] == [0, 1]


async def test_commit_attributes_a_fitbod_source(db_session) -> None:
    user = await _make_user(db_session)
    await _make_exercise(db_session, "Barbell Squat")
    text = _csv("2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0")

    await commit_fitbod_import(
        db_session, user=user, csv_text=text, filename="fitbod.csv"
    )
    await db_session.commit()

    source = (
        await db_session.execute(
            select(DataSource).where(DataSource.name == FITBOD_SOURCE_NAME)
        )
    ).scalar_one_or_none()
    assert source is not None


async def test_commit_lb_units_converted(db_session) -> None:
    user = await _make_user(db_session)
    await _make_exercise(db_session, "Barbell Bench Press - Medium Grip")
    header = (
        "Date,Exercise,Reps,Weight(lbs),Duration(s),Distance(m),"
        "Incline,Resistance,isWarmup,Note,multiplier"
    )
    text = (
        header
        + "\n2021-12-27 10:00:00 +0000,Bench Press,5,225.0,0,0,0,0,false,,1.0\n"
    )
    await commit_fitbod_import(
        db_session, user=user, csv_text=text, filename="fitbod.csv"
    )
    await db_session.commit()

    s = (await db_session.execute(select(TrainingSet))).scalars().one()
    assert s.weight_kg == pytest.approx(102.058, abs=0.01)


async def test_commit_uses_manual_resolution_for_unmatched(db_session) -> None:
    user = await _make_user(db_session)
    custom = await _make_exercise(db_session, "My Cable Thing", user_id=user.id)
    text = _csv(
        "2021-12-27 10:00:00 +0000,Mystery Machine,10,50.0,0,0,0,0,false,,1.0"
    )
    result = await commit_fitbod_import(
        db_session,
        user=user,
        csv_text=text,
        filename="fitbod.csv",
        resolutions={"Mystery Machine": custom.id},
    )
    await db_session.commit()

    assert result.sets_created == 1
    s = (await db_session.execute(select(TrainingSet))).scalars().one()
    assert s.exercise_id == custom.id


async def test_commit_skips_still_unresolved_names(db_session) -> None:
    """A name with no auto-match and no manual resolution is left out, not crashed."""
    user = await _make_user(db_session)
    await _make_exercise(db_session, "Barbell Squat")
    text = _csv(
        "2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0",
        "2021-12-27 10:00:00 +0000,Mystery Machine,10,50.0,0,0,0,0,false,,1.0",
    )
    result = await commit_fitbod_import(
        db_session, user=user, csv_text=text, filename="fitbod.csv"
    )
    await db_session.commit()

    # Only the resolved set was written; the session order is still gap-free.
    assert result.sets_created == 1
    assert result.unresolved_skipped == 1
    s = (await db_session.execute(select(TrainingSet))).scalars().one()
    assert s.order_index == 0


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #


async def test_reimport_same_csv_adds_nothing(db_session) -> None:
    user = await _make_user(db_session)
    await _make_exercise(db_session, "Barbell Squat")
    text = _csv(
        "2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0",
        "2021-12-27 10:00:00 +0000,Back Squat,5,102.5,0,0,0,0,false,,1.0",
    )

    first = await commit_fitbod_import(
        db_session, user=user, csv_text=text, filename="fitbod.csv"
    )
    await db_session.commit()
    assert first.sessions_created == 1
    assert first.sets_created == 2

    second = await commit_fitbod_import(
        db_session, user=user, csv_text=text, filename="fitbod.csv"
    )
    await db_session.commit()
    assert second.sessions_created == 0
    assert second.sets_created == 0

    # Exactly one Session, two Sets after both runs.
    assert (await db_session.execute(select(func.count(TrainingSession.id)))).scalar() == 1
    assert (await db_session.execute(select(func.count(TrainingSet.id)))).scalar() == 2


async def test_reimport_adds_only_new_sessions(db_session) -> None:
    """A second import of an extended export adds only the new workout."""
    user = await _make_user(db_session)
    await _make_exercise(db_session, "Barbell Squat")

    text1 = _csv("2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0")
    await commit_fitbod_import(
        db_session, user=user, csv_text=text1, filename="fitbod.csv"
    )
    await db_session.commit()

    # New file = the old workout PLUS a later one.
    text2 = _csv(
        "2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0",
        "2021-12-29 10:00:00 +0000,Back Squat,5,105.0,0,0,0,0,false,,1.0",
    )
    result = await commit_fitbod_import(
        db_session, user=user, csv_text=text2, filename="fitbod.csv"
    )
    await db_session.commit()

    assert result.sessions_created == 1  # only the 29th
    assert result.sets_created == 1
    assert (await db_session.execute(select(func.count(TrainingSession.id)))).scalar() == 2


async def test_reimport_after_resolving_a_name_does_not_collide(db_session) -> None:
    """Import skipping an unmatched name, then re-import with it resolved.

    Regression for the order_index collision: the first run skips 'Mystery
    Machine' (no match), creating a Session whose sets are indexed over the kept
    rows. The second run resolves the name — but because an existing Session is
    immutable (skipped whole), the re-import must NOT trip the
    (session_id, order_index) unique constraint, and must not duplicate.
    """
    user = await _make_user(db_session)
    await _make_exercise(db_session, "Barbell Squat")
    custom = await _make_exercise(db_session, "My Machine", user_id=user.id)
    # One workout, sets interleaved so resolving the middle name would shift order.
    text = _csv(
        "2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0",
        "2021-12-27 10:00:00 +0000,Mystery Machine,10,50.0,0,0,0,0,false,,1.0",
        "2021-12-27 10:00:00 +0000,Back Squat,5,102.5,0,0,0,0,false,,1.0",
    )

    first = await commit_fitbod_import(
        db_session, user=user, csv_text=text, filename="fitbod.csv"
    )
    await db_session.commit()
    assert first.sessions_created == 1
    assert first.sets_created == 2  # two squats; Mystery skipped
    assert first.unresolved_skipped == 1

    # Re-import the SAME csv, now resolving Mystery Machine. The Session already
    # exists → it is left untouched (no collision, no new rows).
    second = await commit_fitbod_import(
        db_session,
        user=user,
        csv_text=text,
        filename="fitbod.csv",
        resolutions={"Mystery Machine": custom.id},
    )
    await db_session.commit()
    assert second.sessions_created == 0
    assert second.sets_created == 0

    # Still exactly one Session with two Sets, order_index gap-free.
    assert (await db_session.execute(select(func.count(TrainingSet.id)))).scalar() == 2
    sets = (
        await db_session.execute(
            select(TrainingSet).order_by(TrainingSet.order_index)
        )
    ).scalars().all()
    assert [s.order_index for s in sets] == [0, 1]


async def test_reimport_is_per_user_isolated(db_session) -> None:
    """Two users importing the same CSV get their own Sessions (no cross-bleed)."""
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    await _make_exercise(db_session, "Barbell Squat")
    text = _csv("2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0")

    await commit_fitbod_import(
        db_session, user=alice, csv_text=text, filename="fitbod.csv"
    )
    await commit_fitbod_import(
        db_session, user=bob, csv_text=text, filename="fitbod.csv"
    )
    await db_session.commit()

    alice_sessions = (
        await db_session.execute(
            select(func.count(TrainingSession.id)).where(
                TrainingSession.user_id == alice.id
            )
        )
    ).scalar()
    bob_sessions = (
        await db_session.execute(
            select(func.count(TrainingSession.id)).where(
                TrainingSession.user_id == bob.id
            )
        )
    ).scalar()
    assert alice_sessions == 1
    assert bob_sessions == 1


# --------------------------------------------------------------------------- #
# PRs reconciled for imported history
# --------------------------------------------------------------------------- #


async def test_commit_reconciles_personal_records(db_session) -> None:
    user = await _make_user(db_session)
    await _make_exercise(db_session, "Barbell Squat")
    text = _csv(
        "2021-12-27 10:00:00 +0000,Back Squat,5,100.0,0,0,0,0,false,,1.0",
        "2021-12-29 10:00:00 +0000,Back Squat,3,120.0,0,0,0,0,false,,1.0",
    )
    await commit_fitbod_import(
        db_session, user=user, csv_text=text, filename="fitbod.csv"
    )
    await db_session.commit()

    prs = (
        await db_session.execute(
            select(PersonalRecord).where(PersonalRecord.user_id == user.id)
        )
    ).scalars().all()
    assert prs, "expected PRs to be reconciled from imported sets"
    # Best weight PR should be the 120 kg top set.
    weight_prs = [p for p in prs if p.kind.value == "weight"]
    assert weight_prs and weight_prs[0].value == 120.0


async def test_warmup_sets_do_not_seed_prs(db_session) -> None:
    user = await _make_user(db_session)
    await _make_exercise(db_session, "Barbell Squat")
    # Only a warmup set exists → no weight PR should be created from it.
    text = _csv(
        "2021-12-27 10:00:00 +0000,Back Squat,5,60.0,0,0,0,0,true,,1.0",
    )
    await commit_fitbod_import(
        db_session, user=user, csv_text=text, filename="fitbod.csv"
    )
    await db_session.commit()

    prs = (
        await db_session.execute(
            select(PersonalRecord).where(PersonalRecord.user_id == user.id)
        )
    ).scalars().all()
    assert prs == []
