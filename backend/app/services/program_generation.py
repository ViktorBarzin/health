"""Program generation core — deterministic, Principle-derived (ADR-0004).

CONTEXT.md ("Program"): "A generated multi-week training schedule serving the
user's Goal — split structure, ramping weekly per-muscle volume targets,
progression scheme, and Deloads." ADR-0004 is emphatic: the generator composes a
Program **only from the Principles KB**, so *every numeric parameter it chooses
must be read from a Principle's param range* — never a hardcoded number that
duplicates a Principle. This module is that generator, kept **pure** (no DB, no
clock, no LLM — that is #14) like :mod:`app.services.recommendation`: the query
layer fetches the applicable Principles and feeds them in; here we only compute.

How a number is derived (the documented pick rules)
===================================================
For each parameter the generator reads the relevant Principle's ``params`` entry:

* a ``{min, max}`` **range** → the value is the **midpoint, rounded, clamped** to
  the range (deterministic and defensible; the LLM layer #14 may later move within
  the same bounds);
* a ``{value}`` **point** (e.g. the goal-specific rep ranges) → read directly;
* the **effort** target is the **top** of the ``reps_in_reserve`` range (RIR = max,
  i.e. furthest from failure within the evidence window — the conservative,
  fatigue-sparing end the effort Principle endorses).

Every derived number is recorded in :attr:`GeneratedProgram.provenance` as
``{param_name: {principle_key, value, unit, min?, max?}}`` so #14's receipts UI can
answer "why this number" without recomputing. If a *required* Principle is absent
the generator **raises** (it will not invent a number) — a loud, correct failure.

The algorithm
=============
1. Read & record params: volume band, frequency floor, effort, mesocycle length
   (from ``periodization`` when it applies to this context — i.e. is in the
   injected set — else the universal ``deload`` cadence), deload **volume**
   reduction (from the deload rule's *volume* param, not its load one), and the
   goal rep range. The progression *scheme* is the double-progression core; its
   per-set step is a kg increment the core owns, so no percent is faked into the
   receipt.
2. Choose the split from ``days_per_week`` (+ optional style) via
   :mod:`app.services.program_templates`; trim each day's slots to the
   session-length budget **accessories-first** so a day's major-muscle slots are
   always kept. Then **assert** the ``training-frequency`` floor on the BUILT split
   (raises :class:`FrequencyFloorError` on any regression).
3. Build the **ramping** weekly per-muscle volume: weeks ``1..mesocycle_weeks``
   linearly interpolate the volume floor → top (rounded, non-decreasing); the
   trailing **deload** week cuts each muscle to clearly fewer sets than EVERY
   accumulation week — anchored off the week-1 **floor**
   (``round(floor·(1−deload_volume%/100))``, clamped strictly below the floor), so
   the deload is never invisible.
4. Emit a :class:`GeneratedProgram` — header + days + per-(muscle, week) volume.

Determinism: no randomness, no clock; integer rounding is fixed, so the same quiz
+ the same Principles produce byte-identical output (pinned by a test).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.models.principle import ExperienceLevel, TrainingGoal
from app.services.program_templates import (
    MAJOR_MUSCLES,
    SplitStyle,
    split_for,
)


# --------------------------------------------------------------------------- #
# Tunables — the few structural constants that are NOT exercise-science params
# (they shape presentation/packing, not a trained dose). Documented in place.
# --------------------------------------------------------------------------- #

#: Roughly how many minutes one exercise slot (a few working sets + rest) eats, so
#: the session-length answer can cap slots/day. A coarse packing heuristic, not a
#: trained dose — hence local, not a Principle.
_MINUTES_PER_SLOT: int = 12

#: A day always holds at least this many slots (even a very short session does
#: something), and at most this many (a single visit shouldn't sprawl).
_MIN_SLOTS_PER_DAY: int = 2
_MAX_SLOTS_PER_DAY: int = 6


class _PrincipleLike(Protocol):
    """The slice of a Principle the generator reads (key + JSONB params).

    Both the ORM :class:`~app.models.principle.Principle` and the test stand-in
    satisfy this — the core never touches anything else, so it stays pure and
    trivially testable.
    """

    key: str
    params: dict


# --------------------------------------------------------------------------- #
# Inputs / outputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class QuizInput:
    """The guided-quiz answers (or a preset's pinned answers) driving generation.

    ``style`` optionally pins the split shape (a preset uses it); ``preset_key``
    is echoed onto the Program for provenance; ``name`` overrides the generated
    name (a preset supplies its display name).
    """

    goal: TrainingGoal
    experience: ExperienceLevel
    days_per_week: int
    session_minutes: int
    style: SplitStyle | None = None
    preset_key: str | None = None
    name: str | None = None


@dataclass(frozen=True)
class GeneratedDay:
    """One training day of the split: a name and its ordered muscle slots."""

    day_index: int
    name: str
    # Ordered slots as plain dicts (the JSONB shape persisted on ProgramDay).
    slots: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class GeneratedMuscleVolume:
    """A per-muscle weekly volume target for one week (ramps, then deloads)."""

    muscle: str
    week: int
    target_sets: int
    is_deload: bool


@dataclass(frozen=True)
class GeneratedProgram:
    """The deterministic generator's full output for a quiz.

    Header parameters + the split days + the ramping per-(muscle, week) volume,
    plus :attr:`provenance` — the receipt mapping each derived number to its
    Principle. The persistence layer maps this onto the
    :class:`~app.models.program.Program` tables 1:1.
    """

    name: str
    preset_key: str | None
    goal: TrainingGoal
    experience: ExperienceLevel
    days_per_week: int
    session_minutes: int
    mesocycle_weeks: int
    total_weeks: int
    deload_week: int
    rep_range_low: int
    rep_range_high: int
    effort_rir: int
    days: tuple[GeneratedDay, ...]
    muscle_volumes: tuple[GeneratedMuscleVolume, ...]
    provenance: dict[str, dict] = field(default_factory=dict)


class MissingPrincipleError(ValueError):
    """A required Principle (or param) is absent — refuse to invent a number."""


class FrequencyFloorError(ValueError):
    """A built split trains a major muscle below the frequency-Principle floor.

    A guarantee, not an expected path: the authored templates meet the floor at
    every supported day count and session length, so this only fires if a template
    or the slot-capping ever regresses — failing loudly rather than shipping a
    Program that violates ``training-frequency``.
    """


# --------------------------------------------------------------------------- #
# Reading params from the injected Principles
# --------------------------------------------------------------------------- #


def _index(principles: Sequence[_PrincipleLike]) -> dict[str, dict]:
    """Map ``key -> params`` for the injected Principles (last wins on dupes)."""
    return {p.key: p.params for p in principles}


def _param(
    index: dict[str, dict], key: str, name: str
) -> dict[str, Any]:
    """One Principle param entry, or raise if its Principle/param is missing."""
    params = index.get(key)
    if params is None:
        raise MissingPrincipleError(
            f"Program generation needs Principle '{key}' but it is not in the KB"
        )
    entry = params.get(name)
    if entry is None:
        raise MissingPrincipleError(
            f"Principle '{key}' has no parameter '{name}' the generator needs"
        )
    return entry


def _midpoint_int(entry: dict[str, Any]) -> int:
    """Midpoint of a ``{min,max}`` range, rounded to the nearest int, clamped.

    A ``{value}``-only entry returns that value. Used for the "pick within the
    range" rule — deterministic, defensible, mid-of-evidence.
    """
    if "min" in entry and "max" in entry:
        lo, hi = entry["min"], entry["max"]
        mid = (lo + hi) / 2.0
        return max(int(round(lo)), min(int(round(hi)), int(round(mid))))
    if "value" in entry:
        return int(round(entry["value"]))
    raise MissingPrincipleError(f"param entry {entry!r} has neither range nor value")


def _provenance_entry(
    key: str, entry: dict[str, Any], value: float
) -> dict[str, Any]:
    """Build a receipt for a derived value: its source key, value, unit, range."""
    receipt: dict[str, Any] = {"principle_key": key, "value": value}
    if "unit" in entry:
        receipt["unit"] = entry["unit"]
    if "min" in entry:
        receipt["min"] = entry["min"]
    if "max" in entry:
        receipt["max"] = entry["max"]
    return receipt


# --------------------------------------------------------------------------- #
# Sub-steps
# --------------------------------------------------------------------------- #

# Goal → the rep-scheme param name pair the generator reads. A cut preserves
# muscle, so it uses the hypertrophy band; bulk uses hypertrophy; strength the low
# band; maintain the higher band.
_REP_PARAMS: dict[TrainingGoal, tuple[str, str]] = {
    TrainingGoal.strength: ("rep_range_strength_low", "rep_range_strength_high"),
    TrainingGoal.bulk: ("rep_range_hypertrophy_low", "rep_range_hypertrophy_high"),
    TrainingGoal.cut: ("rep_range_hypertrophy_low", "rep_range_hypertrophy_high"),
    TrainingGoal.maintain: ("rep_range_maintain_low", "rep_range_maintain_high"),
}


def _mesocycle_source(index: dict[str, dict]) -> str:
    """Which Principle supplies the mesocycle length, per the KB's applicability.

    The block length comes from ``periodization`` (``mesocycle_weeks``) when that
    rule **applies** to this context, else from the universal ``deload`` cadence
    (``weeks_between_deloads``). Crucially we do NOT re-encode periodization's
    goal/experience applicability here (that would let code and KB diverge): the
    query layer already filtered the injected Principles by ``(goal, experience)``,
    so periodization is simply present in ``index`` iff it applies — read it if
    present, fall back to ``deload`` otherwise.
    """
    return "periodization" if "periodization" in index else "deload"


def _slot_cap(session_minutes: int) -> int:
    """How many exercise slots a day keeps, given the session-length budget."""
    raw = session_minutes // _MINUTES_PER_SLOT
    return max(_MIN_SLOTS_PER_DAY, min(_MAX_SLOTS_PER_DAY, raw))


def _cap_day_muscles(muscles: tuple, slot_cap: int) -> list:
    """Trim a day's muscles to the session-length budget, MAJORS-first.

    A short session can't fit every slot, so we drop **accessory** muscles first
    and keep ALL the day's *major* muscles — preserving each major muscle's weekly
    frequency (the ``training-frequency`` floor) no matter how short the session.
    Original day order is preserved among the muscles kept. If the day has more
    majors than the cap, all majors are still kept (the floor wins over the cap —
    a major muscle is never dropped to hit an arbitrary slot count).
    """
    if len(muscles) <= slot_cap:
        return list(muscles)
    majors = [m for m in muscles if m.value in MAJOR_MUSCLES]
    accessories = [m for m in muscles if m.value not in MAJOR_MUSCLES]
    room = max(0, slot_cap - len(majors))
    kept = set(majors) | set(accessories[:room])
    # Preserve the template's original within-day order.
    return [m for m in muscles if m in kept]


def _build_days(
    days_per_week: int, style: SplitStyle | None, slot_cap: int
) -> tuple[GeneratedDay, ...]:
    """Realise the split template into days, capping each day's slots majors-first.

    Session length trims accessory slots first (``_cap_day_muscles``); a day's
    major-muscle slots are always kept, so the frequency floor survives any
    session length.
    """
    template = split_for(days_per_week, style)
    days: list[GeneratedDay] = []
    for i, day in enumerate(template):
        muscles = _cap_day_muscles(day.muscles, slot_cap)
        slots = [{"muscle": m.value} for m in muscles]
        days.append(GeneratedDay(day_index=i, name=day.name, slots=slots))
    return tuple(days)


def _trained_muscles(days: tuple[GeneratedDay, ...]) -> list[str]:
    """The distinct muscles the split trains, in first-seen order (stable)."""
    seen: list[str] = []
    for d in days:
        for slot in d.slots:
            m = slot["muscle"]
            if m not in seen:
                seen.append(m)
    return seen


def _major_frequencies(days: tuple[GeneratedDay, ...]) -> dict[str, int]:
    """How many built days train each MAJOR muscle (one count per day max)."""
    counts: dict[str, int] = {}
    for d in days:
        majors_today = {
            slot["muscle"] for slot in d.slots if slot["muscle"] in MAJOR_MUSCLES
        }
        for m in majors_today:
            counts[m] = counts.get(m, 0) + 1
    return counts


def _assert_frequency_floor(days: tuple[GeneratedDay, ...], freq_min: int) -> None:
    """Raise if any major muscle the split trains is hit < ``freq_min`` times/week."""
    counts = _major_frequencies(days)
    below = {m: n for m, n in counts.items() if n < freq_min}
    if below:
        raise FrequencyFloorError(
            f"split trains major muscle(s) below the {freq_min}x/week frequency "
            f"floor: {below}"
        )


def _ramp(
    muscles: list[str],
    *,
    start: int,
    top: int,
    mesocycle_weeks: int,
    deload_week: int,
    deload_sets: int,
) -> tuple[GeneratedMuscleVolume, ...]:
    """The ramping weekly per-muscle volume: floor→top over the meso, then deload.

    Accumulation weeks ``1..mesocycle_weeks`` linearly interpolate ``start`` →
    ``top`` (rounded; non-decreasing). The trailing ``deload_week`` sets every
    trained muscle to ``deload_sets``. One row per (muscle, week).
    """
    rows: list[GeneratedMuscleVolume] = []
    span = max(1, mesocycle_weeks - 1)
    for muscle in muscles:
        for week in range(1, mesocycle_weeks + 1):
            # Linear interpolation start→top across the accumulation block.
            frac = (week - 1) / span
            sets = int(round(start + (top - start) * frac))
            rows.append(
                GeneratedMuscleVolume(
                    muscle=muscle, week=week, target_sets=sets, is_deload=False
                )
            )
        rows.append(
            GeneratedMuscleVolume(
                muscle=muscle,
                week=deload_week,
                target_sets=deload_sets,
                is_deload=True,
            )
        )
    return tuple(rows)


def _default_name(goal: TrainingGoal, days_per_week: int) -> str:
    """A human name for a bespoke (non-preset) Program."""
    goal_label = {
        TrainingGoal.bulk: "Hypertrophy",
        TrainingGoal.cut: "Cut",
        TrainingGoal.maintain: "Maintenance",
        TrainingGoal.strength: "Strength",
    }[goal]
    return f"{goal_label} — {days_per_week} days/week"


# --------------------------------------------------------------------------- #
# The generator
# --------------------------------------------------------------------------- #


def generate_program(
    quiz: QuizInput, principles: Sequence[_PrincipleLike]
) -> GeneratedProgram:
    """Generate a Program from quiz answers, deriving every number from Principles.

    ``principles`` are the rules applicable to the quiz's ``(goal, experience)``
    (the query layer fetches them via ``applicable_principles``); this pure core
    reads their param ranges and composes the Program. Raises
    :class:`MissingPrincipleError` if a required Principle/param is absent (it will
    not fabricate a number). Deterministic for fixed inputs.
    """
    index = _index(principles)
    provenance: dict[str, dict] = {}

    # --- Volume band (the ramp's floor and top) ----------------------------- #
    vol = _param(index, "volume-dose-response", "sets_per_muscle_per_week")
    vol_top = int(round(vol["max"])) if "max" in vol else _midpoint_int(vol)
    vol_start = int(round(vol["min"])) if "min" in vol else vol_top
    if vol_start > vol_top:
        vol_start = vol_top
    provenance["weekly_sets_per_muscle_top"] = _provenance_entry(
        "volume-dose-response", vol, vol_top
    )
    provenance["weekly_sets_per_muscle_start"] = _provenance_entry(
        "volume-dose-response", vol, vol_start
    )

    # --- Frequency floor (sessions/muscle/week) ----------------------------- #
    freq = _param(index, "training-frequency", "sessions_per_muscle_per_week")
    freq_min = int(round(freq.get("min", freq.get("value", 2))))
    provenance["frequency_floor"] = _provenance_entry(
        "training-frequency", freq, freq_min
    )

    # --- Effort target (top of the RIR window) ------------------------------ #
    rir = _param(index, "effort-proximity-to-failure", "reps_in_reserve")
    effort_rir = int(round(rir["max"])) if "max" in rir else _midpoint_int(rir)
    provenance["effort_rir"] = _provenance_entry(
        "effort-proximity-to-failure", rir, effort_rir
    )

    # --- Mesocycle length --------------------------------------------------- #
    meso_key = _mesocycle_source(index)
    meso_param = (
        "mesocycle_weeks" if meso_key == "periodization" else "weeks_between_deloads"
    )
    meso_entry = _param(index, meso_key, meso_param)
    mesocycle_weeks = _midpoint_int(meso_entry)
    provenance["mesocycle_weeks"] = _provenance_entry(
        meso_key, meso_entry, mesocycle_weeks
    )

    # --- Deload (timing from the meso length; VOLUME cut from the deload rule) #
    # Read the deload's *volume*-reduction param (not the load one) since the
    # generator reduces set COUNT — so the provenance honestly cites a volume
    # derivation. Anchor the reduction off the ramp's FLOOR (vol_start, week 1),
    # not the top, so the deload prescribes clearly fewer sets than EVERY
    # accumulation week (the top-anchored version coincided with the floor and was
    # invisible). Clamp strictly below the floor (>=1) so a deload always deloads.
    deload_cut = _param(index, "deload", "deload_volume_reduction_percent")
    deload_pct = _midpoint_int(deload_cut)
    deload_sets = int(round(vol_start * (1 - deload_pct / 100.0)))
    deload_sets = max(1, min(deload_sets, vol_start - 1))
    provenance["deload_volume_reduction_percent"] = _provenance_entry(
        "deload", deload_cut, deload_pct
    )
    total_weeks = mesocycle_weeks + 1
    deload_week = total_weeks

    # --- Rep range (goal-specific, from rep-scheme) ------------------------- #
    low_name, high_name = _REP_PARAMS[quiz.goal]
    low_entry = _param(index, "rep-scheme", low_name)
    high_entry = _param(index, "rep-scheme", high_name)
    rep_low = _midpoint_int(low_entry)
    rep_high = _midpoint_int(high_entry)
    provenance["rep_range_low"] = _provenance_entry("rep-scheme", low_entry, rep_low)
    provenance["rep_range_high"] = _provenance_entry(
        "rep-scheme", high_entry, rep_high
    )

    # --- Progression scheme ------------------------------------------------- #
    # The Program progresses each lift via the existing double-progression core
    # (services/progression.py): hold the load, add reps within the range, then add
    # a small load step at the top. We do NOT record progressive-overload's
    # ``load_increase_percent`` in the provenance receipt: that param is a PERCENT,
    # but the per-set step the engine actually applies is the kg increment the
    # Progression core owns (a % can't become a fixed kg until recommendation time,
    # against a real working weight). Advertising the % as a derived number would
    # be a receipt the engine doesn't honour — exactly the dishonesty ADR-0004
    # forbids — so the progression scheme is documented here, not faked as a
    # numeric receipt. (Require the Principle to exist so a goal still composes
    # only from a present KB, but derive no fabricated number from it.)
    _param(index, "progressive-overload", "load_increase_percent")

    # --- Split + per-muscle ramp -------------------------------------------- #
    slot_cap = _slot_cap(quiz.session_minutes)
    days = _build_days(quiz.days_per_week, quiz.style, slot_cap)
    # Enforce the training-frequency floor on the BUILT split (post slot-capping —
    # that's what's actually prescribed): every MAJOR muscle the split trains must
    # be hit >= freq_min times/week. The templates are authored to satisfy this and
    # capping keeps majors, so this never fires for valid input — but it makes the
    # docstring's promise real, failing loudly on any future regression.
    _assert_frequency_floor(days, freq_min)
    muscles = _trained_muscles(days)
    muscle_volumes = _ramp(
        muscles,
        start=vol_start,
        top=vol_top,
        mesocycle_weeks=mesocycle_weeks,
        deload_week=deload_week,
        deload_sets=deload_sets,
    )

    name = quiz.name or _default_name(quiz.goal, quiz.days_per_week)
    return GeneratedProgram(
        name=name,
        preset_key=quiz.preset_key,
        goal=quiz.goal,
        experience=quiz.experience,
        days_per_week=quiz.days_per_week,
        session_minutes=quiz.session_minutes,
        mesocycle_weeks=mesocycle_weeks,
        total_weeks=total_weeks,
        deload_week=deload_week,
        rep_range_low=rep_low,
        rep_range_high=rep_high,
        effort_rir=effort_rir,
        days=days,
        muscle_volumes=muscle_volumes,
        provenance=provenance,
    )


def sets_for_slot(
    weekly_target: int, times_trained_per_week: int
) -> int:
    """Per-session sets for a muscle slot so the weekly target is realised.

    ``ceil(weekly_target / times_trained)`` — distributing the week's volume across
    the days that train the muscle (CONTEXT.md: weekly volume "split across two or
    more sessions"). At least 1 set. Pure helper the recommendation path reuses.
    """
    if times_trained_per_week <= 0:
        return max(1, weekly_target)
    return max(1, math.ceil(weekly_target / times_trained_per_week))
