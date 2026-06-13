"""PR detection — does a freshly-logged Set beat the user's history?

CONTEXT.md ("PR"): "A user's personal record for an Exercise — best weight,
reps-at-weight, estimated 1RM, or volume; detected live as a Set is logged
(offline included) and celebrated in the UI."

This is a **pure** module: ``detect_prs`` takes the candidate Set's numbers plus a
snapshot of the user's prior bests for that Exercise and returns the dimensions
beaten. It holds no DB or I/O, so it is:

* the single shared algorithm definition — the backend calls it to compute and
  persist authoritative PRs on sync (record of truth), and a hand-mirrored TS
  port (``frontend/src/lib/pr.ts``) runs the same logic in the browser so PRs
  fire instantly while **offline**, with no server round-trip;
* trivially testable, with the four dimensions, the normal-only rule and the
  strict-improvement rule pinned by :mod:`tests.test_pr`.

The four PR dimensions (CONTEXT.md):

* **weight**          — heaviest weight lifted, at any rep count;
* **e1rm**            — highest estimated 1RM (see :mod:`app.services.e1rm`);
* **reps_at_weight**  — most reps at a *given* weight (keyed per weight);
* **volume**          — biggest single-set volume load (weight × reps).

Rules, all enforced here so callers (and the TS port) inherit them:

* only **normal** Sets qualify — warmup/drop/failure never PR (the exclusion is
  owned by :func:`app.services.volume.counts_for_volume`, reused here, *not*
  re-listed);
* a PR is a **strict** improvement over the prior best — ties are not PRs;
* a Set with zero weight or zero reps never PRs (a 0-load placeholder is noise);
* against an empty history every applicable dimension is a PR (the first time you
  log an Exercise, that Set is your record on every axis).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class PRKind(str, enum.Enum):
    """The four dimensions a Set can set a personal record on.

    A ``str`` enum (like :class:`~app.models.training_session.SetType`) so it is a
    typed, GROUP-BY-able dimension and serialises to its label on the wire — the
    same labels the TS ``PRKind`` union uses, keeping Py and TS in lockstep.

    Defined *before* the model/service imports below so it is already bound when
    ``app.models.personal_record`` (which keys its native enum column on this
    type) is imported as part of that cascade — otherwise importing this module
    first would deadlock on a partially-initialised ``PRKind`` (circular import).
    """

    weight = "weight"
    e1rm = "e1rm"
    reps_at_weight = "reps_at_weight"
    volume = "volume"


from app.models.training_session import SetType  # noqa: E402
from app.services.e1rm import estimated_1rm  # noqa: E402
from app.services.volume import counts_for_volume  # noqa: E402


@dataclass(frozen=True)
class PriorBests:
    """A snapshot of a user's prior bests for one Exercise (normal Sets only).

    Every field defaults to "nothing logged yet" so an empty ``PriorBests()`` is
    a clean slate on which any qualifying Set is a PR. ``reps_by_weight`` maps an
    exact weight to the most reps ever done at it — the per-weight key for the
    reps-at-weight dimension; a weight absent from the map has never been lifted.
    """

    best_weight_kg: float | None = None
    best_e1rm: float | None = None
    best_volume_kg: float | None = None
    reps_by_weight: dict[float, int] = field(default_factory=dict)


@dataclass(frozen=True)
class PRResult:
    """One PR a Set achieved: the dimension and the value that set it.

    ``at_weight_kg`` is populated only for :attr:`PRKind.reps_at_weight` (the
    weight the rep PR happened at); it is ``None`` for the weight-independent
    dimensions. ``value`` is the achieved figure — the new record — for the UI
    banner ("New 5-rep PR — 100 kg!") and for the persisted record.
    """

    kind: PRKind
    value: float
    at_weight_kg: float | None = None


def _beats(candidate: float, prior: float | None) -> bool:
    """True if ``candidate`` strictly improves on ``prior`` (None = no prior)."""
    return prior is None or candidate > prior


def detect_prs(
    *,
    weight_kg: float,
    reps: int,
    set_type: SetType,
    rir: int | None,
    prior: PriorBests,
) -> list[PRResult]:
    """Return the PRs a just-logged Set sets, given the user's prior bests.

    Keyword-only to keep call sites self-documenting (the weight/reps order is
    easy to flip). Returns an empty list when the Set does not qualify (non-normal
    type, zero load, or zero reps) or beats nothing.
    """
    # Non-normal Sets never PR — single source of the rule is volume.counts_for_volume.
    if not counts_for_volume(set_type):
        return []
    # A zero-load or zero-rep Set carries no signal; never a PR.
    if weight_kg <= 0 or reps <= 0:
        return []

    results: list[PRResult] = []

    # 1. Best weight, at any rep count.
    if _beats(weight_kg, prior.best_weight_kg):
        results.append(PRResult(kind=PRKind.weight, value=weight_kg))

    # 2. Best estimated 1RM (Effort-adjusted via RIR — a set with reserve is
    #    effectively heavier, so it can tip an e1RM PR; see services.e1rm).
    e1rm = estimated_1rm(weight_kg, reps, rir=rir)
    if _beats(e1rm, prior.best_e1rm):
        results.append(PRResult(kind=PRKind.e1rm, value=e1rm))

    # 3. Best reps at THIS exact weight (first ever at a weight always qualifies).
    prior_reps_here = prior.reps_by_weight.get(weight_kg)
    if _beats(reps, prior_reps_here):
        results.append(
            PRResult(
                kind=PRKind.reps_at_weight,
                value=float(reps),
                at_weight_kg=weight_kg,
            )
        )

    # 4. Best single-set volume load (weight × reps).
    volume = weight_kg * reps
    if _beats(volume, prior.best_volume_kg):
        results.append(PRResult(kind=PRKind.volume, value=volume))

    return results
