"""Adherence core — prescribed vs performed (CONTEXT.md "Adherence"; ADR-0011).

Pure and deterministic (the volume.py/effort.py shape): no DB, no clock. Given a
Session's Prescription slots and its performed Sets, measure the gap the Block
Review learns from. The query layer (:mod:`app.services.review_query`) joins the
rows and resolves muscles; this module owns the rules:

- only **normal** Sets count — the same exclusion volume/PR analytics apply
  (:func:`app.services.volume.counts_for_volume` is the single source);
- a rep shortfall **at 0 reps-in-reserve is a hard failure**; with reserve or
  unrated it's a **soft shortfall** — Progression's reserve threshold, reused,
  because failing and choosing to stop are different training signals;
- completion is capped at 1.0 and weighted by prescribed sets; extra
  unprescribed work never inflates or dilutes it (counted separately);
- **no Prescription ⇒ no signal** (``completion=None``) — a freestyle Session
  logged without a plan is not "100% adherent", it's unmeasured.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.models.training_session import SetType
from app.services.volume import counts_for_volume

#: RIR at-or-below which a rep shortfall is a HARD failure (the set was taken to
#: failure and the target still wasn't there) — Progression's reserve threshold.
_FAILURE_RIR: int = 0


@dataclass(frozen=True)
class PrescribedSlot:
    """One slot of a Prescription: what the plan said to do."""

    exercise_id: uuid.UUID
    target_sets: int
    target_reps: int
    target_weight_kg: float
    #: The Program slot's muscle when known (Program path); None for freestyle —
    #: aggregation then falls back to the resolver map.
    muscle: str | None = None


@dataclass(frozen=True)
class PerformedSet:
    """One performed Set, as logged."""

    exercise_id: uuid.UUID
    weight_kg: float
    reps: int
    set_type: str
    rir: int | None = None


@dataclass(frozen=True)
class SlotAdherence:
    """The measured gap for one prescribed slot."""

    exercise_id: uuid.UUID
    muscle: str | None
    prescribed_sets: int
    performed_sets: int
    #: performed/prescribed, capped at 1.0.
    completion: float
    #: Sets short of target reps at RIR 0 — actually failed.
    hard_failures: int
    #: Sets short of target reps with reserve left (or unrated) — chose to stop.
    soft_shortfalls: int
    #: Mean (performed − target)/target weight over this slot's counted sets;
    #: None when the target weight is 0 (bodyweight/starting point) or no sets.
    avg_load_deviation: float | None


@dataclass(frozen=True)
class SessionAdherence:
    """One Session measured against its Prescription."""

    slots: tuple[SlotAdherence, ...]
    #: Weighted by prescribed sets; None when there was no Prescription.
    completion: float | None
    #: Counted (normal) Sets performed beyond any slot's share — extra work.
    extra_sets: int


@dataclass(frozen=True)
class MuscleAdherence:
    """Per-muscle aggregate over one or more Sessions (typically a week)."""

    muscle: str
    prescribed_sets: int
    performed_sets: int
    completion: float
    hard_failures: int
    soft_shortfalls: int


def session_adherence(
    prescribed: Sequence[PrescribedSlot],
    performed: Sequence[PerformedSet],
) -> SessionAdherence:
    """Measure one Session against its Prescription (see module rules)."""
    if not prescribed:
        return SessionAdherence(slots=(), completion=None, extra_sets=0)

    # Counted sets per exercise, in logged order — slots consume from these.
    counted: dict[uuid.UUID, list[PerformedSet]] = {}
    for s in performed:
        try:
            set_type = SetType(s.set_type)
        except ValueError:
            continue
        if not counts_for_volume(set_type):
            continue
        counted.setdefault(s.exercise_id, []).append(s)

    slots: list[SlotAdherence] = []
    consumed: dict[uuid.UUID, int] = {}
    for slot in prescribed:
        pool = counted.get(slot.exercise_id, [])
        start = consumed.get(slot.exercise_id, 0)
        share = pool[start : start + slot.target_sets]
        consumed[slot.exercise_id] = start + len(share)

        hard = 0
        soft = 0
        deviations: list[float] = []
        for s in share:
            if s.reps < slot.target_reps:
                if s.rir is not None and s.rir <= _FAILURE_RIR:
                    hard += 1
                else:
                    soft += 1
            if slot.target_weight_kg > 0:
                deviations.append(
                    (s.weight_kg - slot.target_weight_kg) / slot.target_weight_kg
                )
        slots.append(
            SlotAdherence(
                exercise_id=slot.exercise_id,
                muscle=slot.muscle,
                prescribed_sets=slot.target_sets,
                performed_sets=len(share),
                completion=(
                    min(1.0, len(share) / slot.target_sets)
                    if slot.target_sets > 0
                    else 1.0
                ),
                hard_failures=hard,
                soft_shortfalls=soft,
                avg_load_deviation=(
                    sum(deviations) / len(deviations) if deviations else None
                ),
            )
        )

    total_prescribed = sum(s.prescribed_sets for s in slots)
    total_performed = sum(s.performed_sets for s in slots)
    total_counted = sum(len(v) for v in counted.values())
    return SessionAdherence(
        slots=tuple(slots),
        completion=(
            min(1.0, total_performed / total_prescribed) if total_prescribed else None
        ),
        extra_sets=total_counted - total_performed,
    )


def aggregate_by_muscle(
    sessions: Sequence[SessionAdherence],
    *,
    resolver: Mapping[uuid.UUID, str],
) -> dict[str, MuscleAdherence]:
    """Fold slot adherence into per-muscle totals (a training week, usually).

    A slot's own ``muscle`` wins (Program slots carry it); otherwise the
    ``resolver`` (exercise → primary muscle) fills in; a slot resolvable by
    neither is skipped rather than guessed.
    """
    acc: dict[str, list[SlotAdherence]] = {}
    for session in sessions:
        for slot in session.slots:
            muscle = slot.muscle or resolver.get(slot.exercise_id)
            if muscle is None:
                continue
            acc.setdefault(muscle, []).append(slot)

    out: dict[str, MuscleAdherence] = {}
    for muscle, slots in acc.items():
        prescribed = sum(s.prescribed_sets for s in slots)
        performed = sum(s.performed_sets for s in slots)
        out[muscle] = MuscleAdherence(
            muscle=muscle,
            prescribed_sets=prescribed,
            performed_sets=performed,
            completion=min(1.0, performed / prescribed) if prescribed else 1.0,
            hard_failures=sum(s.hard_failures for s in slots),
            soft_shortfalls=sum(s.soft_shortfalls for s in slots),
        )
    return out
