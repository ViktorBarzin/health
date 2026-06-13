"""Exercise-library seed contract.

The seed upserts the shared (global) Exercise library from free-exercise-db and
must be idempotent — re-running on every boot adds no duplicates, flows changed
fields, and never touches users' custom Exercises. Muscle mappings land in the
normalized, GROUP-BY-able ``exercise_muscles`` table.
"""

from sqlalchemy import func, select

from app.models.exercise import Exercise, ExerciseMuscle, Muscle, MuscleRole
from app.models.user import User
from app.services.seed_exercises import (
    SOURCE_NAME,
    _cdn_image_url,
    _load_dataset,
    seed_exercises,
)

# A tiny in-memory dataset shaped exactly like free-exercise-db records, so seed
# behavior is exercised deterministically without the 870-row file.
_FIXTURE = [
    {
        "id": "Barbell_Bench_Press",
        "name": "Barbell Bench Press",
        "category": "strength",
        "force": "push",
        "level": "beginner",
        "mechanic": "compound",
        "equipment": "barbell",
        "primaryMuscles": ["chest"],
        "secondaryMuscles": ["triceps", "shoulders"],
        "instructions": ["Lie on the bench.", "Press the bar up."],
        "images": ["Barbell_Bench_Press/0.jpg", "Barbell_Bench_Press/1.jpg"],
    },
    {
        "id": "Concentration_Curl",
        "name": "Concentration Curl",
        "category": "strength",
        "force": "pull",
        "level": "beginner",
        "mechanic": "isolation",
        "equipment": "dumbbell",
        "primaryMuscles": ["biceps"],
        "secondaryMuscles": ["forearms"],
        "instructions": ["Curl the dumbbell."],
        "images": ["Concentration_Curl/0.jpg"],
    },
]


async def _count(db, model) -> int:
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def test_seed_inserts_global_exercises_with_muscles(db_session) -> None:
    result = await seed_exercises(db_session, _FIXTURE)

    assert result.inserted == 2
    assert result.updated == 0
    assert await _count(db_session, Exercise) == 2

    bench = (
        await db_session.execute(
            select(Exercise).where(Exercise.slug == "Barbell_Bench_Press")
        )
    ).scalar_one()
    assert bench.user_id is None  # global library row
    assert bench.source == SOURCE_NAME
    assert bench.primary_muscles == ["chest"]
    assert sorted(bench.secondary_muscles) == ["shoulders", "triceps"]
    # Images become full jsDelivr CDN URLs (no bytes vendored in the repo).
    assert all(u.startswith("https://cdn.jsdelivr.net/gh/yuhonas/") for u in bench.images)
    assert bench.images[0] == _cdn_image_url("Barbell_Bench_Press/0.jpg")
    # Demo-video deep link is a deterministic YouTube "proper form" search.
    assert bench.demo_video_url == (
        "https://www.youtube.com/results?search_query=Barbell+Bench+Press+proper+form"
    )


async def test_seed_is_idempotent_no_duplicates(db_session) -> None:
    first = await seed_exercises(db_session, _FIXTURE)
    ex_after_first = await _count(db_session, Exercise)
    mus_after_first = await _count(db_session, ExerciseMuscle)

    second = await seed_exercises(db_session, _FIXTURE)

    assert first.inserted == 2
    # Re-run inserts nothing new and only updates the existing rows in place.
    assert second.inserted == 0
    assert second.updated == 2
    assert await _count(db_session, Exercise) == ex_after_first == 2
    # Muscle mappings are reconciled, not re-appended.
    assert await _count(db_session, ExerciseMuscle) == mus_after_first


async def test_reseed_updates_changed_fields_and_muscles(db_session) -> None:
    await seed_exercises(db_session, _FIXTURE)

    # Same ids, but the dataset changed: bench loses its triceps secondary and
    # gains a level change; curl's instructions are revised.
    revised = [dict(r) for r in _FIXTURE]
    revised[0] = {**revised[0], "level": "intermediate", "secondaryMuscles": ["shoulders"]}
    revised[1] = {**revised[1], "instructions": ["Curl slowly with control."]}

    result = await seed_exercises(db_session, revised)
    assert result.inserted == 0
    assert result.updated == 2

    bench = (
        await db_session.execute(
            select(Exercise).where(Exercise.slug == "Barbell_Bench_Press")
        )
    ).scalar_one()
    assert bench.level == "intermediate"
    # The dropped secondary muscle is gone — reconciled, not duplicated.
    assert bench.secondary_muscles == ["shoulders"]
    assert bench.primary_muscles == ["chest"]

    curl = (
        await db_session.execute(
            select(Exercise).where(Exercise.slug == "Concentration_Curl")
        )
    ).scalar_one()
    assert curl.instructions == ["Curl slowly with control."]


async def test_seed_leaves_custom_exercises_untouched(db_session) -> None:
    user = User(email="lifter@example.com")
    db_session.add(user)
    await db_session.flush()

    custom = Exercise(slug="my-special-move", name="My Special Move", user_id=user.id)
    custom.muscles.append(ExerciseMuscle(muscle=Muscle.chest, role=MuscleRole.primary))
    db_session.add(custom)
    await db_session.flush()

    result = await seed_exercises(db_session, _FIXTURE)

    # Seed only manages global rows; the custom one is neither updated nor counted.
    assert result.inserted == 2
    assert result.updated == 0
    still = (
        await db_session.execute(
            select(Exercise).where(Exercise.id == custom.id)
        )
    ).scalar_one()
    assert still.user_id == user.id
    assert still.name == "My Special Move"
    assert await _count(db_session, Exercise) == 3  # 2 global + 1 custom


async def test_muscle_mappings_are_groupable(db_session) -> None:
    """Muscle is a typed dimension you can GROUP BY (Recovery/analytics later)."""
    await seed_exercises(db_session, _FIXTURE)

    rows = (
        await db_session.execute(
            select(ExerciseMuscle.muscle, func.count())
            .where(ExerciseMuscle.role == MuscleRole.primary)
            .group_by(ExerciseMuscle.muscle)
        )
    ).all()
    counts = {muscle: n for muscle, n in rows}
    assert counts[Muscle.chest] == 1
    assert counts[Muscle.biceps] == 1


async def test_seed_loads_real_vendored_dataset(db_session) -> None:
    """The vendored JSON seeds a sane catalog (~870 exercises) with muscles."""
    dataset = _load_dataset()
    assert len(dataset) >= 800

    result = await seed_exercises(db_session, dataset)
    assert result.inserted >= 800
    assert result.total == len(dataset)
    assert await _count(db_session, Exercise) == len(dataset)

    # The vast majority of exercises carry at least one muscle mapping.
    with_muscles = (
        await db_session.execute(
            select(func.count(func.distinct(ExerciseMuscle.exercise_id)))
        )
    ).scalar_one()
    assert with_muscles >= 800

    # Idempotent on the real dataset too: a second run inserts nothing.
    again = await seed_exercises(db_session, dataset)
    assert again.inserted == 0
    assert await _count(db_session, Exercise) == len(dataset)
