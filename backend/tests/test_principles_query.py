"""Principles query interface contract (#13's generator calls this).

- applicable_principles returns exactly the rules that apply to a (goal,
  experience) context: a universal rule (empty applicability) always applies; a
  goal/level-specific rule only when the context matches; mismatches are excluded.
- A category narrows the result.
- principle_by_key looks one rule up by its stable key (None if unknown).
- The structured params come back so the generator can read a range by name.
"""

import pytest
from sqlalchemy import select

from app.models.principle import (
    EvidenceGrade,
    ExperienceLevel,
    Principle,
    PrincipleCategory,
    PrincipleCitation,
    TrainingGoal,
)
from app.services.principles_query import (
    applicable_principles,
    list_principles,
    principle_by_key,
)


def _principle(
    key: str,
    *,
    category: PrincipleCategory,
    goals: list[str],
    levels: list[str],
    params: dict | None = None,
    grade: EvidenceGrade = EvidenceGrade.A,
) -> Principle:
    return Principle(
        key=key,
        statement=f"Statement for {key}.",
        category=category,
        params=params or {},
        goals=goals,
        experience_levels=levels,
        evidence_grade=grade,
        version=1,
    )


async def _seed(db) -> None:
    """A small mixed KB: one universal rule, goal/level-specific ones."""
    db.add_all(
        [
            # Universal: empty applicability => applies to every context.
            _principle(
                "progressive-overload",
                category=PrincipleCategory.progression,
                goals=[],
                levels=[],
                params={"load_increase_percent": {"min": 2, "max": 10, "unit": "%"}},
            ),
            # Goal-specific: bulk/strength only.
            _principle(
                "volume",
                category=PrincipleCategory.volume,
                goals=[TrainingGoal.bulk.value, TrainingGoal.strength.value],
                levels=[],
                params={"sets_per_muscle_per_week": {"min": 10, "max": 20, "unit": "sets"}},
            ),
            # Goal- and level-specific: strength + intermediate/advanced.
            _principle(
                "periodization",
                category=PrincipleCategory.periodization,
                goals=[TrainingGoal.strength.value, TrainingGoal.bulk.value],
                levels=[
                    ExperienceLevel.intermediate.value,
                    ExperienceLevel.advanced.value,
                ],
            ),
            # Protein for gain goals only (excludes cut).
            _principle(
                "protein",
                category=PrincipleCategory.nutrition,
                goals=[
                    TrainingGoal.bulk.value,
                    TrainingGoal.maintain.value,
                    TrainingGoal.strength.value,
                ],
                levels=[],
            ),
        ]
    )
    await db.flush()


async def test_universal_principle_applies_to_every_context(db_session) -> None:
    await _seed(db_session)
    for goal in TrainingGoal:
        for level in ExperienceLevel:
            keys = {
                p.key
                for p in await applicable_principles(
                    db_session, goal=goal, experience=level
                )
            }
            assert "progressive-overload" in keys


async def test_goal_specific_principle_excluded_for_other_goals(db_session) -> None:
    await _seed(db_session)

    bulk = {
        p.key
        for p in await applicable_principles(
            db_session, goal=TrainingGoal.bulk, experience=ExperienceLevel.beginner
        )
    }
    assert "volume" in bulk  # bulk is in volume's goal set
    assert "protein" in bulk
    # periodization needs intermediate/advanced — excluded for a beginner.
    assert "periodization" not in bulk

    cut = {
        p.key
        for p in await applicable_principles(
            db_session, goal=TrainingGoal.cut, experience=ExperienceLevel.beginner
        )
    }
    # volume and protein are gain-goal rules — excluded for a cut.
    assert "volume" not in cut
    assert "protein" not in cut
    # The universal rule still applies on a cut.
    assert "progressive-overload" in cut


async def test_level_gate_on_periodization(db_session) -> None:
    await _seed(db_session)

    beginner = {
        p.key
        for p in await applicable_principles(
            db_session,
            goal=TrainingGoal.strength,
            experience=ExperienceLevel.beginner,
        )
    }
    assert "periodization" not in beginner

    advanced = {
        p.key
        for p in await applicable_principles(
            db_session,
            goal=TrainingGoal.strength,
            experience=ExperienceLevel.advanced,
        )
    }
    assert "periodization" in advanced


async def test_category_filter_narrows_result(db_session) -> None:
    await _seed(db_session)
    rows = await applicable_principles(
        db_session,
        goal=TrainingGoal.bulk,
        experience=ExperienceLevel.advanced,
        category=PrincipleCategory.volume,
    )
    assert [p.key for p in rows] == ["volume"]


async def test_goal_only_context_ignores_experience(db_session) -> None:
    """Passing only a goal does not filter on experience."""
    await _seed(db_session)
    keys = {
        p.key for p in await applicable_principles(db_session, goal=TrainingGoal.strength)
    }
    # periodization has a level gate but no experience was supplied, so it's in.
    assert {"progressive-overload", "volume", "periodization", "protein"} == keys


async def test_principle_by_key_returns_one_with_params(db_session) -> None:
    await _seed(db_session)
    p = await principle_by_key(db_session, "volume")
    assert p is not None
    assert p.category == PrincipleCategory.volume
    # The structured range is readable by name — what the generator consumes.
    rng = p.params["sets_per_muscle_per_week"]
    assert rng["min"] == 10 and rng["max"] == 20 and rng["unit"] == "sets"


async def test_principle_by_key_unknown_is_none(db_session) -> None:
    await _seed(db_session)
    assert await principle_by_key(db_session, "does-not-exist") is None


async def test_applies_to_model_method_matches_query(db_session) -> None:
    """Principle.applies_to agrees with the SQL applicability filter."""
    await _seed(db_session)
    rows = {p.key: p for p in await list_principles(db_session)}
    # Universal rule applies everywhere.
    assert rows["progressive-overload"].applies_to(
        TrainingGoal.cut, ExperienceLevel.beginner
    )
    # Goal-specific volume excludes a cut.
    assert not rows["volume"].applies_to(TrainingGoal.cut, ExperienceLevel.beginner)
    # periodization needs an advanced/intermediate level.
    assert not rows["periodization"].applies_to(
        TrainingGoal.strength, ExperienceLevel.beginner
    )
    assert rows["periodization"].applies_to(
        TrainingGoal.strength, ExperienceLevel.advanced
    )


async def test_eager_loaded_citations_available(db_session) -> None:
    """A looked-up Principle carries its citations in one round trip."""
    p = _principle(
        "volume-cited",
        category=PrincipleCategory.volume,
        goals=[],
        levels=[],
        params={"sets_per_muscle_per_week": {"min": 10, "max": 20, "unit": "sets"}},
    )
    p.citations.append(
        PrincipleCitation(
            authors="Schoenfeld BJ, et al.",
            year=2017,
            title="Dose-response volume meta-analysis",
            journal="Journal of Sports Sciences",
            doi="10.1080/02640414.2016.1210197",
            pmid="27433992",
        )
    )
    db_session.add(p)
    await db_session.flush()
    db_session.expunge_all()

    fetched = await principle_by_key(db_session, "volume-cited")
    assert fetched is not None
    assert len(fetched.citations) == 1
    assert fetched.citations[0].pmid == "27433992"


async def test_list_principles_returns_all_ordered(db_session) -> None:
    await _seed(db_session)
    rows = await list_principles(db_session)
    assert len(rows) == 4
    # Ordered by (category, key) — category is a native enum, so it sorts by the
    # enum's declaration order (volume < progression < periodization < nutrition),
    # a stable, deterministic browse order.
    assert [p.key for p in rows] == [
        "volume",
        "progressive-overload",
        "periodization",
        "protein",
    ]
