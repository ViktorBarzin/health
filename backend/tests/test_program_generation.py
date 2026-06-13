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

import copy
from dataclasses import dataclass

import pytest

from app.models.principle import ExperienceLevel, TrainingGoal
from app.services.program_generation import (
    FrequencyFloorError,
    MissingPrincipleError,
    QuizInput,
    generate_program,
)
from app.services.program_presets import PRESETS, preset_by_key
from app.services.seed_principles import PRINCIPLES


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
    """The generator's inputs, built FROM the real seeded KB (no drift).

    Derived directly from :data:`app.services.seed_principles.PRINCIPLES` rather
    than hand-duplicating param ranges, so a change to the real KB flows into these
    tests automatically and a stale stub can never hide real-KB drift inside a
    coarse range. We pass *all* rules (regardless of goal applicability) — the pure
    core's job is the maths; the query layer owns applicability and is covered by
    the API tests. ``test_default_principles_match_seeded_kb`` re-asserts the link.
    """
    return [
        FakePrinciple(seed.key, copy.deepcopy(seed.params)) for seed in PRINCIPLES
    ]


def _without(key: str) -> list[FakePrinciple]:
    """The default principles minus the one with ``key`` (for missing-rule tests)."""
    return [p for p in _default_principles() if p.key != key]


def _with_param(key: str, params: dict) -> list[FakePrinciple]:
    """The default principles with ``key``'s params REPLACED (for perturbation tests)."""
    return [
        FakePrinciple(key, params) if p.key == key else p
        for p in _default_principles()
    ]


# The Principle keys the generator REQUIRES (reads a param from). Each must be
# present or generation raises — pinned by test_missing_any_required_principle.
_REQUIRED_KEYS = [
    "volume-dose-response",
    "training-frequency",
    "effort-proximity-to-failure",
    "deload",
    "rep-scheme",
    "progressive-overload",
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
    lo = generate_program(_quiz(), _default_principles())
    lo_top = max(v.target_sets for v in lo.muscle_volumes if not v.is_deload)

    hi = generate_program(
        _quiz(),
        _with_param(
            "volume-dose-response",
            {"sets_per_muscle_per_week": {"min": 4, "max": 6, "unit": "sets"}},
        ),
    )
    hi_top = max(v.target_sets for v in hi.muscle_volumes if not v.is_deload)
    assert hi_top <= 6 < lo_top


def test_changing_rep_principle_changes_generated_reps() -> None:
    base = generate_program(_quiz(goal=TrainingGoal.bulk), _default_principles())
    changed = generate_program(
        _quiz(goal=TrainingGoal.bulk),
        _with_param(
            "rep-scheme",
            {
                "rep_range_hypertrophy_low": {"value": 20, "unit": "reps"},
                "rep_range_hypertrophy_high": {"value": 30, "unit": "reps"},
            },
        ),
    )
    assert changed.rep_range_low == 20 and changed.rep_range_high == 30
    assert base.rep_range_low != changed.rep_range_low


def test_changing_effort_principle_changes_generated_effort() -> None:
    # Effort = top of the RIR range; widen the range and the target moves with it.
    base = generate_program(_quiz(), _default_principles())
    changed = generate_program(
        _quiz(),
        _with_param(
            "effort-proximity-to-failure",
            {"reps_in_reserve": {"min": 0, "max": 1, "unit": "RIR"}},
        ),
    )
    assert changed.effort_rir == 1
    assert base.effort_rir != changed.effort_rir


def test_changing_mesocycle_principle_changes_length() -> None:
    # Mesocycle length is the midpoint of periodization's range; shift it and the
    # number (and total_weeks/deload_week) move with it.
    base = generate_program(_quiz(), _default_principles())
    changed = generate_program(
        _quiz(),
        _with_param(
            "periodization",
            {"mesocycle_weeks": {"min": 8, "max": 12, "unit": "weeks"}},
        ),
    )
    assert changed.mesocycle_weeks == 10
    assert changed.total_weeks == 11 and changed.deload_week == 11
    assert base.mesocycle_weeks != changed.mesocycle_weeks


def test_changing_deload_volume_principle_changes_deload_depth() -> None:
    # The deload set count is derived from deload_volume_reduction_percent; deepen
    # the cut and the deload week prescribes even fewer sets.
    base = generate_program(_quiz(), _default_principles())
    base_dl = next(v.target_sets for v in base.muscle_volumes if v.is_deload)
    deeper = generate_program(
        _quiz(),
        _with_param(
            "deload",
            {
                "weeks_between_deloads": {"min": 4, "max": 8, "unit": "weeks"},
                "deload_volume_reduction_percent": {
                    "min": 70,
                    "max": 90,
                    "unit": "%",
                },
            },
        ),
    )
    deeper_dl = next(v.target_sets for v in deeper.muscle_volumes if v.is_deload)
    assert deeper_dl < base_dl
    assert deeper.provenance["deload_volume_reduction_percent"]["principle_key"] == "deload"


def test_changing_frequency_floor_is_enforced() -> None:
    # Raise the frequency floor above what any split can deliver → the generator
    # refuses (FrequencyFloorError) rather than shipping a non-compliant Program.
    with pytest.raises(FrequencyFloorError):
        generate_program(
            _quiz(days_per_week=4),
            _with_param(
                "training-frequency",
                {"sessions_per_muscle_per_week": {"min": 5, "unit": "sessions"}},
            ),
        )


# --------------------------------------------------------------------------- #
# Split structure matches days/week + frequency floor
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("days", [2, 3, 4, 5, 6])
def test_split_has_one_day_per_training_day(days) -> None:
    prog = generate_program(_quiz(days_per_week=days), _default_principles())
    assert len(prog.days) == days
    # day_index is gap-free 0..days-1.
    assert sorted(d.day_index for d in prog.days) == list(range(days))


def _freq_floor_from_kb() -> int:
    """The frequency floor as the real KB defines it (no hardcoded 2)."""
    seed = next(s for s in PRINCIPLES if s.key == "training-frequency")
    return int(seed.params["sessions_per_muscle_per_week"]["min"])


@pytest.mark.parametrize("days", [2, 3, 4, 5, 6])
@pytest.mark.parametrize("session_minutes", [30, 45, 60, 75, 90])
def test_frequency_floor_met_for_every_major_muscle(days, session_minutes) -> None:
    # EVERY major muscle the split trains is hit >= the floor the Principle defines
    # — no `if m in counts` escape hatch — across all day counts AND session
    # lengths (so the slot-cap can't drop a major below the floor).
    floor = _freq_floor_from_kb()
    prog = generate_program(
        _quiz(days_per_week=days, session_minutes=session_minutes),
        _default_principles(),
    )
    counts = _major_muscle_day_counts(prog)
    assert counts, (days, session_minutes)  # the split trains some major muscles
    for muscle, n in counts.items():
        assert n >= floor, (muscle, n, floor, days, session_minutes)


def _major_muscle_day_counts(prog) -> dict[str, int]:
    """How many days train each MAJOR muscle (one count per day max)."""
    from app.services.program_templates import MAJOR_MUSCLES

    counts: dict[str, int] = {}
    for d in prog.days:
        for m in {s["muscle"] for s in d.slots if s["muscle"] in MAJOR_MUSCLES}:
            counts[m] = counts.get(m, 0) + 1
    return counts


def test_full_body_3day_meets_floor_and_ppl3_is_not_offered() -> None:
    # The 3-day default (full body) hits each major muscle 3x; a PPL@3 (which would
    # train each muscle once) is NOT in the catalog, so pinning PPL at 3 days falls
    # back to the compliant full-body split rather than shipping a 1x/week program.
    from app.services.program_templates import SplitStyle, split_for

    prog = generate_program(
        _quiz(days_per_week=3, style=SplitStyle.push_pull_legs), _default_principles()
    )
    counts = _major_muscle_day_counts(prog)
    floor = _freq_floor_from_kb()
    for muscle, n in counts.items():
        assert n >= floor, (muscle, n)
    # The fallback used the full-body template, not a 1x PPL.
    assert split_for(3, SplitStyle.push_pull_legs) == split_for(3, SplitStyle.full_body)


def test_session_length_caps_slots_per_day() -> None:
    # A shorter session yields no more slots/day than a longer one (accessories are
    # trimmed first), but a day is never empty and majors are always kept (the
    # frequency-floor test covers the majors-kept invariant across all lengths).
    short = generate_program(_quiz(session_minutes=30), _default_principles())
    long = generate_program(_quiz(session_minutes=90), _default_principles())
    max_short = max(len(d.slots) for d in short.days)
    max_long = max(len(d.slots) for d in long.days)
    assert max_short <= max_long
    assert min(len(d.slots) for d in short.days) >= 1  # never an empty day


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
    # Accumulation weeks are non-decreasing and end above where they start (a real
    # ramp, not flat).
    sets = [v.target_sets for v in accumulation]
    assert sets == sorted(sets)
    assert sets[-1] > sets[0]
    # Exactly one deload week, and it cuts volume below EVERY accumulation week —
    # crucially below WEEK 1 (the floor), not merely below the top, so the deload
    # is never invisible (the bug: top-anchored cut landed on the week-1 floor).
    assert len(deload) == 1
    assert deload[0].week == prog.total_weeks
    assert deload[0].target_sets < min(sets), (deload[0].target_sets, sets)


def test_deload_is_fewer_sets_than_week_one_for_all_goals() -> None:
    # The deload-below-week-1 invariant holds for every goal (the real KB yields a
    # week-1 floor of 10 and a ~40% volume cut → ~6, clearly fewer).
    for goal in TrainingGoal:
        prog = generate_program(_quiz(goal=goal), _default_principles())
        per_muscle: dict[str, dict[int, int]] = {}
        for v in prog.muscle_volumes:
            per_muscle.setdefault(v.muscle, {})[v.week] = v.target_sets
        for muscle, by_week in per_muscle.items():
            week1 = by_week[1]
            deload = by_week[prog.deload_week]
            assert deload < week1, (goal, muscle, deload, week1)


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


@pytest.mark.parametrize("missing_key", _REQUIRED_KEYS)
def test_missing_any_required_principle_raises(missing_key) -> None:
    # Dropping ANY required Principle (not just volume) must fail loudly with a
    # MissingPrincipleError — the generator never invents a number (ADR-0004). This
    # covers every key the generator reads, so a future "silently default" mistake
    # on any of them is caught.
    with pytest.raises(MissingPrincipleError):
        generate_program(_quiz(), _without(missing_key))


def test_default_principles_match_seeded_kb() -> None:
    # The pure-core test fixture IS the real seeded KB (built from PRINCIPLES), so
    # this guards against drift: if the test stubs ever diverge from the real KB,
    # this fails. Concretely, the specific params the generator reads must carry the
    # exact ranges the real seed defines.
    by_key = {p.key: p.params for p in _default_principles()}
    assert by_key["volume-dose-response"]["sets_per_muscle_per_week"] == {
        "min": 10,
        "max": 20,
        "unit": "sets",
    }
    assert by_key["training-frequency"]["sessions_per_muscle_per_week"]["min"] == 2
    assert by_key["effort-proximity-to-failure"]["reps_in_reserve"]["max"] == 3
    # The deload VOLUME param (not the load one) exists and is what's read.
    assert "deload_volume_reduction_percent" in by_key["deload"]
    # Every required key is actually present in the seeded KB.
    for key in _REQUIRED_KEYS:
        assert key in by_key, key
