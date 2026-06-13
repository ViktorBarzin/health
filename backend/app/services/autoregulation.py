"""Autoregulation: adjust today's prescription on Readiness + Recovery (#14).

CONTEXT.md (Program / Recommendation): "the daily Recommendation is drawn from
the active Program and **autoregulated by Recovery and Readiness** — the user's
edits always win." This pure module is that autoregulator. ADR-0002/0004 fix the
engine as deterministic and explainable; this is the last piece that closes the
loop:

    log → Recovery + Readiness → autoregulated, cited, Goal-driven Program → workout

Like :mod:`app.services.recovery` and :mod:`app.services.readiness` it is a
**pure** core — no DB, no clock, no LLM. The query layer
(:mod:`app.services.program_recommendation`) builds the generated slots, computes
Readiness and Recovery, marks which slots the user has edited, and feeds them in.

What it does
============
Given the day's generated slots (each carrying its **Principle volume bounds** —
the per-muscle weekly floor and ceiling the generator derived), today's biometric
**Readiness** (0–100, or ``None`` when there's no signal), and the per-muscle
**Recovery** map (0–100), it scales each slot's set count by a factor combining:

* a **readiness factor** — at/above the "ready" band it's 1.0 (and a *strong*
  reading with fresh muscles may allow a small bump, never past the ceiling);
  below the band it falls linearly toward :data:`_MIN_READINESS_FACTOR` at zero
  readiness, so trimming is **monotonic** in readiness;
* a **recovery factor** — a muscle whose Recovery is below
  :data:`_RECOVERY_FULL_AT` is trimmed proportionally (a still-fatigued muscle
  loses more sets than a fresh one), down to :data:`_MIN_RECOVERY_FACTOR`.

The scaled count is rounded and **clamped into the Principle bounds**
(``[max(1, floor), ceiling]``) — autoregulation moves *within* the evidence
window the generator already established; it never trims below a sensible floor
nor exceeds the volume ceiling (ADR-0004's "within Principle bounds"). Reps and
weight are left to the Progression core; autoregulation is a **volume** lever
(trim top sets / keep / allow slightly more), which is the standard, defensible
in-session autoregulation knob.

The hard invariant: **a user-edited slot is returned untouched** — autoregulation
adjusts only the engine's own generated targets. Anything the user explicitly set
or logged passes straight through, even above the ceiling.

It also owns two small, related pure decisions used by the same query layer:

* :func:`early_deload_triggered` — should fatigue trigger a deload *earlier* than
  the calendar one? True when readiness has been **persistently** low (a run of
  recent days below the threshold), not on a single rough day.
* :func:`reflow_day_index` — the next-due training day after **missed** days:
  the rotation follows the count of Sessions actually done, so skipping days
  doesn't stall the split on the same day.

Every threshold lives at the top as a documented constant.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# --------------------------------------------------------------------------- #
# Tunable thresholds — the single place to retune autoregulation.
# --------------------------------------------------------------------------- #

#: At/above this Readiness the day is "ready" — no readiness-driven trim (factor
#: 1.0). Below it, volume is trimmed, scaling linearly to the floor at 0.
_READY_AT: float = 60.0

#: At/above this Readiness *and* with fresh muscles the day may be allowed a
#: small volume bump (still clamped under the ceiling).
_STRONG_AT: float = 85.0

#: The readiness factor at *zero* readiness — the most we ever trim from
#: readiness alone (0.5 ⇒ halve the prescribed sets at rock-bottom readiness).
_MIN_READINESS_FACTOR: float = 0.5

#: The small extra volume a strong, fresh day may add (capped under the ceiling).
_STRONG_BONUS_FACTOR: float = 1.15

#: A muscle at/above this Recovery is "fresh" — no recovery-driven trim. Below
#: it, that muscle's volume scales down proportionally.
_RECOVERY_FULL_AT: float = 70.0

#: The recovery factor at *zero* recovery — the most we trim a maximally-fatigued
#: muscle (independent of readiness).
_MIN_RECOVERY_FACTOR: float = 0.5

#: Below this combined factor a slot counts as "trimmed" (so a sub-1-set rounding
#: nudge isn't reported as an adjustment). A factor at/above ~0.999 is "kept".
_KEEP_EPSILON: float = 1e-3

# Early-deload trigger.
#: Readiness at/below this counts as a "low" day.
_DELOAD_LOW_READINESS: float = 45.0
#: This many low days within the recent window triggers an early deload.
_DELOAD_MIN_LOW_DAYS: int = 3
#: …considered over at most this many of the most-recent signals.
_DELOAD_WINDOW: int = 5


@dataclass(frozen=True)
class AdjustableSlot:
    """One prescribed exercise slot the autoregulator may scale.

    ``sets``/``reps``/``weight_kg`` are the generated targets; ``muscle`` is the
    slot's primary muscle (keys into the Recovery map). ``sets_floor`` /
    ``sets_ceiling`` are the **Principle** per-muscle weekly bounds the generator
    derived (autoregulation clamps within them). ``user_edited`` marks a slot the
    user has explicitly changed or logged against — such a slot is returned
    untouched. ``key`` is a stable identifier the caller maps back to its
    Exercise (defaults to the muscle for the simple one-slot-per-muscle case).
    """

    key: str
    muscle: str
    sets: int
    reps: int
    weight_kg: float
    sets_floor: int
    sets_ceiling: int
    user_edited: bool = False


@dataclass(frozen=True)
class AdjustmentResult:
    """The autoregulated day: adjusted slots plus the human-readable reason.

    ``adjusted`` is true iff at least one generated slot's set count changed.
    ``reason`` is the plain-English explanation the UI shows ("Readiness 48/100 —
    HRV below your baseline; trimmed top sets"); empty when nothing changed and
    readiness was unremarkable. ``readiness`` echoes the signal used (or ``None``).
    """

    slots: tuple[AdjustableSlot, ...]
    adjusted: bool
    reason: str
    readiness: float | None = None
    trimmed_muscles: tuple[str, ...] = field(default_factory=tuple)


def _readiness_factor(readiness: float | None) -> float:
    """Volume multiplier from Readiness alone (monotonic, 1.0 when ready).

    ``None`` (no signal) ⇒ 1.0 (no biometric trim). At/above :data:`_READY_AT`
    ⇒ 1.0. Below it, linearly down to :data:`_MIN_READINESS_FACTOR` at 0.
    """
    if readiness is None:
        return 1.0
    if readiness >= _READY_AT:
        return 1.0
    # Linear from MIN_FACTOR at 0 to 1.0 at _READY_AT.
    frac = max(0.0, readiness) / _READY_AT
    return _MIN_READINESS_FACTOR + (1.0 - _MIN_READINESS_FACTOR) * frac


def _recovery_factor(recovery: float | None) -> float:
    """Volume multiplier for one muscle from its Recovery (1.0 when fresh).

    ``None`` (untrained / no fatigue) ⇒ 1.0. At/above :data:`_RECOVERY_FULL_AT`
    ⇒ 1.0. Below it, linearly down to :data:`_MIN_RECOVERY_FACTOR` at 0.
    """
    if recovery is None or recovery >= _RECOVERY_FULL_AT:
        return 1.0
    frac = max(0.0, recovery) / _RECOVERY_FULL_AT
    return _MIN_RECOVERY_FACTOR + (1.0 - _MIN_RECOVERY_FACTOR) * frac


def _trim_floor(slot: AdjustableSlot) -> int:
    """How far down a trim may go: the Principle floor, but never *raising* the
    generated value.

    The floor constrains a downward trim only. A slot whose generated set count is
    already at or below the Principle floor (e.g. a **deload** week, a deliberate
    cut below the accumulation band) is never pulled back *up* — that would erase
    the deload — so the effective trim floor is ``min(floor, generated sets)``,
    and always at least one working set.
    """
    return max(1, min(slot.sets_floor, slot.sets))


def _adjust_slot(
    slot: AdjustableSlot,
    *,
    readiness: float | None,
    recovery: dict[str, float],
) -> AdjustableSlot:
    """Scale one generated slot's set count, direction-aware, within Principle bounds.

    User-edited slots are returned unchanged. Autoregulation only ever moves a
    slot *away* from its generated value in the direction the signals indicate:

    * a **trim** (combined factor < 1) reduces sets, clamped no lower than
      :func:`_trim_floor` (so a trim can't go below the Principle floor *nor*
      raise an already-reduced deload value);
    * a **strong, fresh** day bumps sets up by a small factor, clamped no higher
      than the Principle ceiling (and never below the generated value);
    * otherwise (factor ≈ 1, unremarkable readiness) the slot is unchanged.
    """
    if slot.user_edited:
        return slot

    muscle_recovery = recovery.get(slot.muscle)

    # Strong, fresh day: allow a small bump, capped at the ceiling.
    if (
        readiness is not None
        and readiness >= _STRONG_AT
        and (muscle_recovery is None or muscle_recovery >= _RECOVERY_FULL_AT)
    ):
        target = int(round(slot.sets * _STRONG_BONUS_FACTOR))
        target = min(target, max(slot.sets_ceiling, slot.sets))
        target = max(slot.sets, target)  # a bump never reduces
        return replace(slot, sets=target)

    factor = _readiness_factor(readiness) * _recovery_factor(muscle_recovery)
    if factor >= 1.0:
        # No trim warranted — leave the generated value (incl. a deload) intact.
        return slot
    target = int(round(slot.sets * factor))
    target = max(_trim_floor(slot), min(slot.sets, target))  # a trim never raises
    return replace(slot, sets=target)


def _build_reason(
    readiness: float | None,
    trimmed: list[str],
    raised: bool,
) -> tuple[bool, str]:
    """Compose the human-readable reason. Returns ``(adjusted, reason)``."""
    if trimmed:
        muscles = ", ".join(trimmed)
        if readiness is not None:
            head = f"Readiness {round(readiness)}/100"
            return True, (
                f"{head} — trimmed top sets to protect recovery "
                f"({muscles})."
            )
        return True, (
            f"Some muscles are still fatigued — trimmed top sets ({muscles})."
        )
    if raised and readiness is not None:
        return True, (
            f"Readiness {round(readiness)}/100 — feeling strong; "
            f"added a little volume."
        )
    if readiness is not None and readiness >= _STRONG_AT:
        # Strong day but already at the ceiling: flag it positively, no change.
        return False, (
            f"Readiness {round(readiness)}/100 — good to go; "
            f"the planned volume stands."
        )
    return False, ""


def autoregulate_day(
    slots: list[AdjustableSlot],
    *,
    readiness: float | None,
    recovery: dict[str, float],
) -> AdjustmentResult:
    """Autoregulate the day's slots on Readiness + per-muscle Recovery.

    Trims (or, on a strong fresh day, slightly raises) each *generated* slot's
    set count within its Principle bounds; **user-edited slots pass through
    untouched**. Emits a plain-English reason mentioning the readiness number when
    it trims. Deterministic — pure function of its inputs.
    """
    adjusted_slots: list[AdjustableSlot] = []
    trimmed: list[str] = []
    raised = False
    for slot in slots:
        new = _adjust_slot(slot, readiness=readiness, recovery=recovery)
        adjusted_slots.append(new)
        if slot.user_edited:
            continue
        if new.sets < slot.sets:
            trimmed.append(slot.muscle)
        elif new.sets > slot.sets:
            raised = True

    adjusted, reason = _build_reason(readiness, trimmed, raised)
    return AdjustmentResult(
        slots=tuple(adjusted_slots),
        adjusted=adjusted,
        reason=reason,
        readiness=readiness,
        trimmed_muscles=tuple(dict.fromkeys(trimmed)),
    )


def early_deload_triggered(recent_readiness: list[float | None]) -> bool:
    """Whether persistently low Readiness should trigger an early deload.

    ``recent_readiness`` is the most-recent-last (or most-recent-first — only the
    count matters) list of daily Readiness scores, ``None`` for days with no
    signal (skipped, not counted). Fires when at least
    :data:`_DELOAD_MIN_LOW_DAYS` of the last :data:`_DELOAD_WINDOW` *available*
    readings are at/below :data:`_DELOAD_LOW_READINESS` — a sustained low, not a
    single rough day. Deterministic.
    """
    available = [r for r in recent_readiness if r is not None]
    if len(available) < _DELOAD_MIN_LOW_DAYS:
        return False
    window = available[-_DELOAD_WINDOW:]
    low_days = sum(1 for r in window if r <= _DELOAD_LOW_READINESS)
    return low_days >= _DELOAD_MIN_LOW_DAYS


def reflow_day_index(*, sessions_done: int, days_per_week: int) -> int:
    """Next-due training-day index after (possibly) missed days.

    The split rotates by how many Sessions the user has actually completed, so
    skipped days don't stall the rotation on the same day:
    ``sessions_done mod days_per_week``. Defensive against a degenerate 0
    days/week (returns 0). Deterministic.
    """
    if days_per_week <= 0:
        return 0
    return sessions_done % days_per_week
