"""Progression: the per-Exercise next-target core (effort-gated double progression).

CONTEXT.md ("Progression"): "The per-exercise next-target logic ('last time
80kg×8 → try 82.5kg×8') derived from that exercise's Set history." This is the
deterministic engine core (ADR-0002) the freestyle Recommendation generator (#11)
consumes to fill each prescribed Set's weight × reps.

The method — **effort-gated double progression**
=================================================
Double progression is the standard, well-evidenced scheme for a fixed rep range
(e.g. 8–12): you keep the **load** constant and add **reps** session to session
until you reach the top of the range, then add a small load increment and reset
to the bottom. The "effort gate" (Zourdos 2016 RIR/RPE; Refalo 2023 0–3-RIR
effort zone) decides *when* the load may go up: you only bump load if the
top-of-range set was reached with reps **in reserve** — i.e. it was within
capacity, not a grind to failure. A set taken to failure (RIR 0) at the top is
strong but offers no headroom, so we bank it (hold) before adding load.

Concretely, reading the **most recent working set** for the Exercise:

* **reps below the bottom of the range**
    * to failure (RIR 0) → the load was too heavy: **back off** one increment,
      target the bottom of the range;
    * with reserve (RIR ≥ 1, or unrated) → **hold** the load, target the bottom
      (build the reps up — a bad day, not too-heavy a load);
* **reps within the range but below the top** → **add a rep** (hold load),
  capped at the top of the range — the add-reps phase;
* **reps at or above the top of the range**
    * with reserve (RIR ≥ 1) → **add load** one increment, reset reps to the
      bottom — the load-increase phase;
    * to failure (RIR 0) → **hold** load, stay at the top (capped) — bank the
      top-end rep quality before progressing the load;
    * **unrated** (Effort missing) → **add load** — the rep-only fallback can't
      see reserve, so hitting the top *is* the trigger (CONTEXT.md: "when Effort
      is missing it falls back to rep performance alone — rating is never
      required").

With no history at all, there is no working weight to progress from, so the
target is the bottom of the range at weight 0 (the UI reads 0 as "enter a
weight" / bodyweight) — flagged ``is_starting_point`` so the generator/UI can
treat it as a first guess. A caller may seed a starting weight.

Properties (pinned in :mod:`tests.test_progression`)
----------------------------------------------------
* the next **load** is monotonic non-decreasing in both reps performed and reps
  in reserve — a better-performed set never prescribes a *lighter* next load.
  Note the right lens: a single-set *e1RM* is deliberately **not** monotonic
  here, because the load-increase phase resets reps to the bottom (e.g. at the
  top of the range RIR 0 → 60×12 holds at a higher e1RM than RIR 1 → 62.5×8 —
  the heavier load for fewer reps *is* the progression). So the pinned invariant
  is on the prescribed load + rep-target axes, not on e1RM;
* the rep target always stays within ``[low, high]``; load only changes in whole
  increments and never goes negative;
* unrated history never *requires* a rating — it degrades to a rep-only rule.

Pure module: no DB, no clock, no I/O — the querying layer
(:mod:`app.services.recommendation_query`) turns a user's stored Sets into
:class:`SetPerformance` inputs and the generator consumes the result.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Tunable defaults — the single place to retune Progression. See module docstring.
# --------------------------------------------------------------------------- #

#: The working rep range for a normal hypertrophy-oriented Set: add reps within
#: it, add load at its top. 8–12 is the canonical hypertrophy range and a sane
#: general default; callers (a Program, later) may pass a strength-style range.
DEFAULT_REP_RANGE: tuple[int, int] = (8, 12)

#: The load step added (or backed off) when progressing past the top of the
#: range. 2.5 kg is the smallest jump loadable from a standard 1.25 kg plate pair
#: (one per side) — the finest real-world barbell increment, so prescriptions
#: stay loadable on a default Gym Profile.
DEFAULT_LOAD_INCREMENT_KG: float = 2.5

#: RIR strictly below this counts as "to failure / no reserve" for the effort
#: gate. RIR 0 (RPE 10) is failure; RIR ≥ 1 leaves at least one rep in reserve.
_RESERVE_RIR_THRESHOLD: int = 1


@dataclass(frozen=True)
class SetPerformance:
    """One prior working Set's performance, the Progression input unit.

    ``weight_kg`` × ``reps`` is what was lifted; ``rir`` is the logged Effort as
    reps-in-reserve (the one-tap chip value 0–4, or ``None`` when the Set carries
    no Effort). The querying layer builds these from the most recent *normal*
    Sets for the Exercise (most-recent-first); this module never touches the ORM.
    """

    weight_kg: float
    reps: int
    rir: int | None = None


@dataclass(frozen=True)
class ProgressionTarget:
    """The next prescribed target for an Exercise: a weight × reps to aim for.

    ``is_starting_point`` is ``True`` only when there is no usable history, so
    the weight is a guess (0 = "enter a weight"/bodyweight unless the caller
    seeded one) rather than a progression off a real working set.
    """

    weight_kg: float
    reps: int
    is_starting_point: bool = False


def _has_reserve(rir: int | None) -> bool:
    """Whether the Set left reps in reserve (not a to-failure grind).

    ``None`` (unrated) is treated as *no known reserve* so the rep-only fallback
    drives the decision rather than an assumed effort.
    """
    return rir is not None and rir >= _RESERVE_RIR_THRESHOLD


def next_target(
    history: Sequence[SetPerformance],
    *,
    rep_range: tuple[int, int] = DEFAULT_REP_RANGE,
    load_increment_kg: float = DEFAULT_LOAD_INCREMENT_KG,
    starting_weight_kg: float = 0.0,
) -> ProgressionTarget:
    """Next weight × reps target for an Exercise via effort-gated double progression.

    ``history`` is the Exercise's recent working-set performances, **most recent
    first**; only the most recent is used to progress from (the generator passes
    the latest normal Set). With an empty history a starting prescription is
    returned (bottom of range at ``starting_weight_kg``). See the module
    docstring for the full rule table.
    """
    low, high = rep_range

    # No usable history → a starting guess at the bottom of the range.
    if not history:
        return ProgressionTarget(
            weight_kg=max(0.0, starting_weight_kg),
            reps=low,
            is_starting_point=True,
        )

    last = history[0]
    weight = last.weight_kg
    reps = last.reps
    has_reserve = _has_reserve(last.rir)
    unrated = last.rir is None

    # --- Below the bottom of the range -------------------------------------- #
    if reps < low:
        if not has_reserve and not unrated:
            # To failure and still short of the range → load too heavy: back off.
            return ProgressionTarget(
                weight_kg=max(0.0, weight - load_increment_kg), reps=low
            )
        # Reserve left (or unrated) → hold the load and rebuild the reps.
        return ProgressionTarget(weight_kg=weight, reps=low)

    # --- At or above the top of the range ----------------------------------- #
    if reps >= high:
        # Add load when there was reserve, OR when unrated (rep-only fallback:
        # hitting the top is the trigger). Hold (cap at top) only when we KNOW it
        # was to failure (rated RIR 0).
        if has_reserve or unrated:
            return ProgressionTarget(
                weight_kg=weight + load_increment_kg, reps=low
            )
        return ProgressionTarget(weight_kg=weight, reps=high)

    # --- Within the range, below the top → add a rep (capped at the top) ----- #
    return ProgressionTarget(weight_kg=weight, reps=min(reps + 1, high))
