"""Program generation core — the deterministic generator's contract (ADR-0004).

This pins the engine-core guarantees the spec mandates:

* every numeric parameter the generator chooses is **derived from a Principle's
  param range** (asserted within the cited range) and is **traceable** via
  provenance to that Principle's key — and if a Principle's range changes, the
  generated value changes (we inject the Principles, so the test proves it);
* the **split structure matches days/week** and meets the **frequency floor**
  (each major muscle trained >= the Principle minimum);
* the **weekly per-muscle volume ramps** across the mesocycle then **deloads**;
* each **preset** produces the expected shape (days + goal-appropriate rep range).

Pure core: no DB, no clock — Principles are passed in as lightweight stand-ins, so
the maths is unit-testable in isolation (the query layer feeds real ORM rows).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.models.exercise import Muscle
from app.models.principle import ExperienceLevel, TrainingGoal
from app.services.program_generation import (
    QuizInput,
    generate_program,
)
from app.services.program_presets import PRESETS, preset_by_key


# --------------------------------------------------------------------------- #
# A tiny stand-in for the Principle ORM model: the generator only reads .key and
# .params, so a frozen dataclass with those two attributes is enough (and lets a
# test mutate a range to prove generation tracks it).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FakePrinciple:
    key: str
    params: dict


def _default_principles() -> list[FakePrinciple]:
    """The subset of the real KB params the generator reads (current values)."""
    return [
        FakePrinciple(
            "volume-dose-response",
            {"sets_per_muscle_per_week": {"min": 10, "max": 20, "unit": "sets"}},
        ),
        FakePrinciple(
            "training-frequency",
            {"sessions_per_muscle_per_week": {"min": 2, "unit": "sessions"}},
        ),
        FakePrinciple(
            "effort-proximity-to-failure",
            {"reps_in_reserve": {"min": 0, "max": 3, "unit": "RIR"}},
        ),
        FakePrinciple(
            "periodization",
            {"mesocycle_weeks": {"min": 4, "max": 8, "unit": "weeks"}},
        ),
        FakePrinciple(
            "progressive-overload",
            {"load_increase_percent": {"min": 2, "max": 10, "unit": "%"}},
        ),
        FakePrinciple(
            "deload",
            {
                "weeks_between_deloads": {"min": 4, "max": 8, "unit": "weeks"},
                "deload_load_reduction_percent": {"min": 40, "max": 60, "unit": "%"},
            },
        ),
        FakePrinciple(
            "rep-scheme",
            {
                "rep_range_strength_low": {"value": 3, "unit": "reps"},
                "rep_range_strength_high": {"value": 6, "unit": "reps"},
                "rep_range_hypertrophy_low": {"value": 6, "unit": "reps"},
                "rep_range_hypertrophy_high": {"value": 12, "unit": "reps"},
                "rep_range_maintain_low": {"value": 8, "unit": "reps"},
                "rep_range_maintain_high": {"value": 15, "unit": "reps"},
            },
        ),
    ]


def _quiz(**kw) -> QuizInput:
    base = dict(
        goal=TrainingGoal.bulk,
        experience=ExperienceLevel.intermediate,
        days_per_week=4,
        session_minutes=70,
    )
    base.update(kw)
    return QuizInput(**base)


# --------------------------------------------------------------------------- #
# Provenance: every number traces to a Principle, within its range
# --------------------------------------------------------------------------- #


def test_volume_target_within_principle_range_and_traced() -> None:
    prog = generate_program(_quiz(), _default_principles())
    # The mesocycle volume top each muscle ramps to lies within 10-20 sets.
    top = max(v.target_sets for v in prog.muscle_volumes if not v.is_deload)
    assert 10 <= top <= 20
    # …and it is traced to the volume principle.
    prov = prog.provenance["weekly_sets_per_muscle_top"]
    assert prov["principle_key"] == "volume-dose-response"
    assert prov["min"] == 10 and prov["max"] == 20


def test_effort_target_within_principle_range_and_traced() -> None:
    prog = generate_program(_quiz(), _default_principles())
    assert 0 <= prog.effort_rir <= 3
    assert prog.provenance["effort_rir"]["principle_key"] == "effort-proximity-to-failure"


def test_mesocycle_length_within_principle_range_and_traced() -> None:
    prog = generate_program(_quiz(), _default_principles())
    assert 4 <= prog.mesocycle_weeks <= 8
    src = prog.provenance["mesocycle_weeks"]["principle_key"]
    # bulk+intermediate => periodization applies; else deload supplies the cadence.
    assert src in {"periodization", "deload"}


def test_rep_range_traced_to_rep_scheme() -> None:
    prog = generate_program(_quiz(goal=TrainingGoal.bulk), _default_principles())
    assert prog.provenance["rep_range_low"]["principle_key"] == "rep-scheme"
    assert prog.provenance["rep_range_high"]["principle_key"] == "rep-scheme"


def test_every_provenance_entry_names_a_known_principle() -> None:
    principles = _default_principles()
    keys = {p.key for p in principles}
    prog = generate_program(_quiz(), principles)
    for param, entry in prog.provenance.items():
        assert entry["principle_key"] in keys, param
        assert "value" in entry


# --------------------------------------------------------------------------- #
# Generation TRACKS the Principles: change a range, the output changes
# --------------------------------------------------------------------------- #


def test_changing_volume_principle_changes_generated_volume() -> None:
    # If the KB says 4-6 sets instead of 10-20, the generated top drops with it —
    # proving the number is derived, not hardcoded.
    principles = _default_principles()
    lo = generate_program(_quiz(), principles)
    lo_top = max(v.target_sets for v in lo.muscle_volumes if not v.is_deload)

    tweaked = [
        FakePrinciple(
            "volume-dose-response",
            {"sets_per_muscle_per_week": {"min": 4, "max": 6, "unit": "sets"}},
        )
        if p.key == "volume-dose-response"
        else p
        for p in principles
    ]
    hi = generate_program(_quiz(), tweaked)
    hi_top = max(v.target_sets for v in hi.muscle_volumes if not v.is_deload)
    assert hi_top <= 6 < lo_top


def test_changing_rep_principle_changes_generated_reps() -> None:
    principles = _default_principles()
    base = generate_program(_quiz(goal=TrainingGoal.bulk), principles)
    tweaked = [
        FakePrinciple(
            "rep-scheme",
            {
                "rep_range_hypertrophy_low": {"value": 20, "unit": "reps"},
                "rep_range_hypertrophy_high": {"value": 30, "unit": "reps"},
            },
        )
        if p.key == "rep-scheme"
        else p
        for p in principles
    ]
    changed = generate_program(_quiz(goal=TrainingGoal.bulk), tweaked)
    assert changed.rep_range_low == 20 and changed.rep_range_high == 30
    assert base.rep_range_low != changed.rep_range_low


# --------------------------------------------------------------------------- #
# Split structure matches days/week + frequency floor
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("days", [2, 3, 4, 5, 6])
def test_split_has_one_day_per_training_day(days) -> None:
    prog = generate_program(_quiz(days_per_week=days), _default_principles())
    assert len(prog.days) == days
    # day_index is gap-free 0..days-1.
    assert sorted(d.day_index for d in prog.days) == list(range(days))


@pytest.mark.parametrize("days", [2, 3, 4, 5, 6])
def test_frequency_floor_met_for_major_muscles(days) -> None:
    # Every major muscle the split trains is hit >= the frequency floor (2x/wk).
    prog = generate_program(_quiz(days_per_week=days), _default_principles())
    counts: dict[str, int] = {}
    for d in prog.days:
        for slot in d.slots:
            counts[slot["muscle"]] = counts.get(slot["muscle"], 0) + 1
    majors = {
        Muscle.chest.value,
        Muscle.lats.value,
        Muscle.quadriceps.value,
        Muscle.shoulders.value,
    }
    for m in majors:
        if m in counts:
            assert counts[m] >= 2, (m, counts[m], days)


def test_session_length_caps_slots_per_day() -> None:
    short = generate_program(_quiz(session_minutes=30), _default_principles())
    long = generate_program(_quiz(session_minutes=90), _default_principles())
    max_short = max(len(d.slots) for d in short.days)
    max_long = max(len(d.slots) for d in long.days)
    assert max_short <= max_long
    assert max_short >= 1  # never an empty day


# --------------------------------------------------------------------------- #
# Volume ramps, then deloads
# --------------------------------------------------------------------------- #


def test_weekly_volume_ramps_then_deloads() -> None:
    prog = generate_program(_quiz(), _default_principles())
    # Pick a muscle the split trains.
    muscle = prog.muscle_volumes[0].muscle
    series = sorted(
        (v for v in prog.muscle_volumes if v.muscle == muscle),
        key=lambda v: v.week,
    )
    accumulation = [v for v in series if not v.is_deload]
    deload = [v for v in series if v.is_deload]
    # Accumulation weeks are non-decreasing and end at/above where they start.
    sets = [v.target_sets for v in accumulation]
    assert sets == sorted(sets)
    assert sets[-1] >= sets[0]
    # There's exactly one deload week, and it cuts volume below the meso top.
    assert len(deload) == 1
    assert deload[0].week == prog.total_weeks
    assert deload[0].target_sets < sets[-1]


def test_deload_week_is_last_and_total_weeks_consistent() -> None:
    prog = generate_program(_quiz(), _default_principles())
    assert prog.deload_week == prog.total_weeks
    assert prog.total_weeks == prog.mesocycle_weeks + 1
    # Every trained muscle has a row for every week 1..total_weeks.
    weeks = sorted({v.week for v in prog.muscle_volumes})
    assert weeks == list(range(1, prog.total_weeks + 1))


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_generation_is_deterministic() -> None:
    a = generate_program(_quiz(), _default_principles())
    b = generate_program(_quiz(), _default_principles())
    assert a == b


# --------------------------------------------------------------------------- #
# Goal-specific rep ranges
# --------------------------------------------------------------------------- #


def test_strength_goal_uses_low_rep_range() -> None:
    prog = generate_program(
        _quiz(goal=TrainingGoal.strength, experience=ExperienceLevel.intermediate),
        _default_principles(),
    )
    assert prog.rep_range_low == 3 and prog.rep_range_high == 6


def test_bulk_goal_uses_hypertrophy_rep_range() -> None:
    prog = generate_program(
        _quiz(goal=TrainingGoal.bulk), _default_principles()
    )
    assert prog.rep_range_low == 6 and prog.rep_range_high == 12


def test_maintain_goal_uses_maintain_rep_range() -> None:
    prog = generate_program(
        _quiz(goal=TrainingGoal.maintain), _default_principles()
    )
    assert prog.rep_range_low == 8 and prog.rep_range_high == 15


def test_cut_goal_uses_hypertrophy_rep_range() -> None:
    # A cut preserves muscle, so it mirrors the hypertrophy band.
    prog = generate_program(
        _quiz(goal=TrainingGoal.cut), _default_principles()
    )
    assert prog.rep_range_low == 6 and prog.rep_range_high == 12


# --------------------------------------------------------------------------- #
# Presets are pinned parameterizations of the SAME generator
# --------------------------------------------------------------------------- #


def test_all_presets_generate_a_valid_program() -> None:
    for preset in PRESETS:
        prog = generate_program(
            _quiz(
                goal=preset.goal,
                experience=preset.experience,
                days_per_week=preset.days_per_week,
                session_minutes=preset.session_minutes,
                style=preset.style,
                preset_key=preset.key,
            ),
            _default_principles(),
        )
        assert prog.preset_key == preset.key
        assert len(prog.days) == preset.days_per_week
        assert prog.total_weeks == prog.mesocycle_weeks + 1


def test_gzclp_preset_is_strength_low_reps_3_day() -> None:
    preset = preset_by_key("gzclp")
    assert preset is not None
    prog = generate_program(
        _quiz(
            goal=preset.goal,
            experience=preset.experience,
            days_per_week=preset.days_per_week,
            session_minutes=preset.session_minutes,
            style=preset.style,
            preset_key=preset.key,
        ),
        _default_principles(),
    )
    assert prog.goal == TrainingGoal.strength
    assert prog.rep_range_high <= 6  # strength rep band
    assert len(prog.days) == 3


def test_ppl_preset_is_six_day_split() -> None:
    preset = preset_by_key("ppl-hypertrophy")
    assert preset is not None
    prog = generate_program(
        _quiz(
            goal=preset.goal,
            experience=preset.experience,
            days_per_week=preset.days_per_week,
            session_minutes=preset.session_minutes,
            style=preset.style,
            preset_key=preset.key,
        ),
        _default_principles(),
    )
    assert len(prog.days) == 6
    assert {d.name for d in prog.days} == {
        "Push A",
        "Pull A",
        "Legs A",
        "Push B",
        "Pull B",
        "Legs B",
    }


# --------------------------------------------------------------------------- #
# Missing-principle guard (a defensible failure, not a hardcoded silent default)
# --------------------------------------------------------------------------- #


def test_missing_required_principle_raises() -> None:
    # Drop the volume principle → the generator cannot derive volume from the KB,
    # so it must fail loudly rather than invent a number (ADR-0004).
    principles = [p for p in _default_principles() if p.key != "volume-dose-response"]
    with pytest.raises(Exception):
        generate_program(_quiz(), principles)
