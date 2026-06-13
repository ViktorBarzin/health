"""Volume helpers — the canonical "what counts" rule for Sets.

CONTEXT.md ("Set"): "Non-normal types are excluded from volume and PR statistics
by default." PR detection and analytics are later slices, but the rule has to
live somewhere central *now* so those slices inherit the exclusion instead of
re-deriving (and risking diverging from) it.

Volume here is the standard training-volume proxy **weight × reps** ("volume
load") for a single Set, summed by the caller. Only ``normal`` Sets contribute;
warmup / drop / failure Sets are logged but never counted by default.
"""

from collections.abc import Iterable

from app.models.training_session import SetType, TrainingSet


def counts_for_volume(set_type: SetType) -> bool:
    """Whether a Set of this type contributes to volume/PR stats by default.

    Only ``normal`` counts. This is the single source of truth for the CONTEXT.md
    non-normal exclusion; later PR/analytics slices call this rather than
    re-listing the excluded types.
    """
    return set_type == SetType.normal


def set_volume(weight_kg: float, reps: int, set_type: SetType) -> float:
    """Volume-load contribution of one Set: ``weight_kg × reps``, or 0 if excluded.

    A non-normal Set (warmup/drop/failure) contributes 0 by default, so callers
    can sum unconditionally over a mixed list of Sets.
    """
    if not counts_for_volume(set_type):
        return 0.0
    return weight_kg * reps


def session_volume(sets: Iterable[TrainingSet]) -> float:
    """Total counted volume load for a Session's Sets.

    Sums ``weight_kg × reps`` over the ``normal`` Sets only; non-normal Sets are
    excluded per the CONTEXT.md default.
    """
    return sum(s.weight_kg * s.reps for s in sets if counts_for_volume(s.set_type))
