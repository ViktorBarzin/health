"""PR persistence service — the authoritative record-of-truth on the backend.

The pure detector (:mod:`app.services.pr`) decides *whether* a Set is a PR; this
service wires it to the DB: it reads the user's prior normal-Set history for the
Exercise, runs detection, and upserts the authoritative
:class:`~app.models.personal_record.PersonalRecord` rows. These tests use a real
Postgres (the ORM is Postgres-specific) and assert:

* a first Set persists a record on every dimension;
* a beating Set advances the stored record (and only the beaten dimensions);
* a non-beating / tie Set persists nothing new;
* non-normal Sets are ignored;
* recomputation is idempotent and never double-counts (the reconciliation
  guarantee — the same set processed twice yields one row per slot).
"""

import uuid

import pytest
from sqlalchemy import select

from app.models.exercise import Exercise
from app.models.personal_record import PersonalRecord
from app.models.training_session import SetType, TrainingSession, TrainingSet
from app.models.user import User
from app.services.pr import PRKind
from app.services.pr_service import detect_and_persist_prs, prior_bests_for


async def _user(db, email="alice@example.com") -> User:
    u = User(email=email)
    db.add(u)
    await db.flush()
    return u


async def _exercise(db, name="Bench Press") -> Exercise:
    ex = Exercise(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        source="free-exercise-db",
    )
    db.add(ex)
    await db.flush()
    return ex


async def _session(db, user) -> TrainingSession:
    s = TrainingSession(user_id=user.id)
    db.add(s)
    await db.flush()
    return s


async def _add_set(
    db, session, exercise, *, weight, reps, set_type=SetType.normal, order=0
) -> TrainingSet:
    s = TrainingSet(
        session_id=session.id,
        exercise_id=exercise.id,
        order_index=order,
        weight_kg=weight,
        reps=reps,
        set_type=set_type,
    )
    db.add(s)
    await db.flush()
    return s


async def _records(db, user, exercise) -> dict:
    rows = (
        await db.execute(
            select(PersonalRecord).where(
                PersonalRecord.user_id == user.id,
                PersonalRecord.exercise_id == exercise.id,
            )
        )
    ).scalars().all()
    # Key by (kind, weight_bucket) — the natural slot.
    return {(r.kind, r.weight_bucket): r for r in rows}


async def test_first_set_persists_a_record_on_each_dimension(db_session) -> None:
    user = await _user(db_session)
    ex = await _exercise(db_session)
    sess = await _session(db_session, user)
    s = await _add_set(db_session, sess, ex, weight=100.0, reps=5)

    prs = await detect_and_persist_prs(db_session, s)
    assert {p.kind for p in prs} == {
        PRKind.weight,
        PRKind.e1rm,
        PRKind.reps_at_weight,
        PRKind.volume,
    }

    recs = await _records(db_session, user, ex)
    # Four rows: three weight-independent (bucket None) + one reps_at_weight @100.
    assert (PRKind.weight, None) in recs
    assert (PRKind.e1rm, None) in recs
    assert (PRKind.volume, None) in recs
    assert (PRKind.reps_at_weight, 100.0) in recs
    assert recs[(PRKind.weight, None)].value == pytest.approx(100.0)
    assert recs[(PRKind.volume, None)].value == pytest.approx(500.0)
    assert recs[(PRKind.reps_at_weight, 100.0)].value == pytest.approx(5)
    assert recs[(PRKind.weight, None)].achieved_set_id == s.id


async def test_beating_set_advances_only_beaten_dimensions(db_session) -> None:
    user = await _user(db_session)
    ex = await _exercise(db_session)
    sess = await _session(db_session, user)

    first = await _add_set(db_session, sess, ex, weight=100.0, reps=5, order=0)
    await detect_and_persist_prs(db_session, first)

    # 100 × 6: same weight (no weight PR), but more reps@100, higher e1RM, more vol.
    second = await _add_set(db_session, sess, ex, weight=100.0, reps=6, order=1)
    prs = await detect_and_persist_prs(db_session, second)
    kinds = {p.kind for p in prs}
    assert PRKind.weight not in kinds  # same 100 kg, not heavier
    assert PRKind.reps_at_weight in kinds
    assert PRKind.e1rm in kinds
    assert PRKind.volume in kinds

    recs = await _records(db_session, user, ex)
    # Weight record unchanged at 100, still pointing at the first set.
    assert recs[(PRKind.weight, None)].value == pytest.approx(100.0)
    assert recs[(PRKind.weight, None)].achieved_set_id == first.id
    # Reps@100 advanced to 6, pointing at the second set.
    assert recs[(PRKind.reps_at_weight, 100.0)].value == pytest.approx(6)
    assert recs[(PRKind.reps_at_weight, 100.0)].achieved_set_id == second.id


async def test_non_beating_set_persists_nothing_new(db_session) -> None:
    user = await _user(db_session)
    ex = await _exercise(db_session)
    sess = await _session(db_session, user)

    big = await _add_set(db_session, sess, ex, weight=200.0, reps=5, order=0)
    await detect_and_persist_prs(db_session, big)
    before = await _records(db_session, user, ex)

    # A clearly weaker set: 50 × 3. Beats nothing (new weight bucket 50 though!).
    weak = await _add_set(db_session, sess, ex, weight=50.0, reps=3, order=1)
    prs = await detect_and_persist_prs(db_session, weak)
    # 50 kg is a new weight bucket → reps_at_weight@50 IS a (first-at-weight) PR,
    # but weight/e1rm/volume are all beaten by the 200×5 history.
    assert {p.kind for p in prs} == {PRKind.reps_at_weight}

    after = await _records(db_session, user, ex)
    # The three weight-independent records are untouched.
    assert after[(PRKind.weight, None)].value == before[(PRKind.weight, None)].value
    assert after[(PRKind.e1rm, None)].value == before[(PRKind.e1rm, None)].value
    assert after[(PRKind.volume, None)].value == before[(PRKind.volume, None)].value


async def test_tie_is_not_a_pr(db_session) -> None:
    user = await _user(db_session)
    ex = await _exercise(db_session)
    sess = await _session(db_session, user)

    a = await _add_set(db_session, sess, ex, weight=100.0, reps=5, order=0)
    await detect_and_persist_prs(db_session, a)
    # Identical set: ties everything, beats nothing.
    b = await _add_set(db_session, sess, ex, weight=100.0, reps=5, order=1)
    prs = await detect_and_persist_prs(db_session, b)
    assert prs == []


async def test_non_normal_set_is_ignored(db_session) -> None:
    user = await _user(db_session)
    ex = await _exercise(db_session)
    sess = await _session(db_session, user)

    s = await _add_set(
        db_session, sess, ex, weight=300.0, reps=10, set_type=SetType.warmup
    )
    prs = await detect_and_persist_prs(db_session, s)
    assert prs == []
    assert await _records(db_session, user, ex) == {}


async def test_history_excludes_other_users(db_session) -> None:
    alice = await _user(db_session, "alice@example.com")
    bob = await _user(db_session, "bob@example.com")
    ex = await _exercise(db_session)

    a_sess = await _session(db_session, alice)
    a_set = await _add_set(db_session, a_sess, ex, weight=150.0, reps=5)
    await detect_and_persist_prs(db_session, a_set)

    # Bob's first set on the same Exercise is HIS first — a PR for him, despite
    # Alice's heavier history.
    b_sess = await _session(db_session, bob)
    b_set = await _add_set(db_session, b_sess, ex, weight=60.0, reps=5)
    prs = await detect_and_persist_prs(db_session, b_set)
    assert PRKind.weight in {p.kind for p in prs}


async def test_idempotent_no_double_rows(db_session) -> None:
    # The reconciliation guarantee: re-processing the same set must not create
    # duplicate rows or "double-count" — one row per slot, same values, same
    # set pointer. (Detection always excludes the candidate set from its own
    # history, so re-running re-derives it as the holder rather than tying it —
    # which is exactly right for reconciliation: the truth is recomputed.)
    user = await _user(db_session)
    ex = await _exercise(db_session)
    sess = await _session(db_session, user)
    s = await _add_set(db_session, sess, ex, weight=120.0, reps=3)

    await detect_and_persist_prs(db_session, s)
    first = await _records(db_session, user, ex)
    assert len(first) == 4  # weight, e1rm, volume (bucket None) + reps@120

    # Re-run: same slots, same values, no extra rows, still pointing at this set.
    await detect_and_persist_prs(db_session, s)
    second = await _records(db_session, user, ex)
    assert set(first.keys()) == set(second.keys())
    assert len(second) == 4
    for slot, rec in second.items():
        assert rec.value == pytest.approx(first[slot].value)
        assert rec.achieved_set_id == s.id


async def test_prior_bests_reflects_history(db_session) -> None:
    # The helper that feeds the pure detector reads only this user's normal Sets
    # for this Exercise, excluding the given set id.
    user = await _user(db_session)
    ex = await _exercise(db_session)
    sess = await _session(db_session, user)

    await _add_set(db_session, sess, ex, weight=100.0, reps=5, order=0)
    await _add_set(db_session, sess, ex, weight=120.0, reps=3, order=1)
    await _add_set(
        db_session, sess, ex, weight=500.0, reps=20, set_type=SetType.failure, order=2
    )
    candidate = await _add_set(db_session, sess, ex, weight=80.0, reps=8, order=3)

    prior = await prior_bests_for(
        db_session, user_id=user.id, exercise_id=ex.id, exclude_set_id=candidate.id
    )
    # Heaviest normal weight is 120 (the 500 failure set is excluded).
    assert prior.best_weight_kg == pytest.approx(120.0)
    # reps_by_weight has the two normal weights, not 80 (candidate excluded) nor 500.
    assert prior.reps_by_weight == {100.0: 5, 120.0: 3}
    # Best volume among normal history: 120×3=360 vs 100×5=500 → 500.
    assert prior.best_volume_kg == pytest.approx(500.0)
