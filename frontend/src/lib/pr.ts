/**
 * PR detection + e1RM — the browser-side mirror of the backend pure cores.
 *
 * This is a hand-mirrored port of `backend/app/services/e1rm.py` and
 * `backend/app/services/pr.py`. It runs PR detection in the browser so a
 * personal record fires **instantly while logging — offline included** (the app
 * is offline-first; ADR-0005), with no server round-trip. The backend re-runs
 * the same algorithm on sync as the record-of-truth and reconciles any
 * client-side celebration that turns out to be wrong.
 *
 * The two implementations are kept provably in agreement by mirrored test suites
 * (`pr.test.ts` here, `tests/test_e1rm.py` + `tests/test_pr.py` on the backend) —
 * the same cases, the same expected outcomes. If you change the formula or a PR
 * rule, change it in BOTH and update both suites.
 *
 * The four PR dimensions (CONTEXT.md "PR"):
 *   weight          — heaviest weight, at any reps
 *   e1rm            — highest estimated 1RM
 *   reps_at_weight  — most reps at a given weight (keyed per weight)
 *   volume          — biggest single-set volume load (weight × reps)
 *
 * Rules (identical to the backend): only `normal` sets qualify; a PR is a STRICT
 * improvement (ties don't count); a zero-load or zero-rep set never PRs; against
 * an empty history every applicable dimension is a PR.
 */

import type { SetType } from './types';

/** Epley's denominator constant — one formula, one place (matches e1rm.py). */
const EPLEY_DIVISOR = 30;

/**
 * 1-rep-anchored Epley estimate for `weightKg` lifted for `reps` reps.
 *
 * Uses `(reps - 1)` so a single returns the weight exactly (the boundary PR
 * detection relies on). Returns 0 if either input is 0; throws on negatives —
 * mirroring `epley_1rm` in e1rm.py.
 */
export function epley1rm(weightKg: number, reps: number): number {
  if (weightKg < 0) throw new Error(`weightKg must be >= 0, got ${weightKg}`);
  if (reps < 0) throw new Error(`reps must be >= 0, got ${reps}`);
  if (weightKg === 0 || reps === 0) return 0;
  return weightKg * (1 + (reps - 1) / EPLEY_DIVISOR);
}

/**
 * Estimated 1RM for a set, optionally adjusted for reps in reserve (RIR).
 *
 * A positive RIR makes the set effectively heavier (`effectiveReps = reps +
 * rir`) so the estimate rises and never falls; `rir` of 0 (to failure) or
 * null/undefined (not rated) leaves the plain Epley result. Mirrors
 * `estimated_1rm` in e1rm.py.
 */
export function estimated1rm(
  weightKg: number,
  reps: number,
  rir: number | null = null,
): number {
  if (rir != null && rir < 0) throw new Error(`rir must be >= 0, got ${rir}`);
  const effectiveReps = reps + (rir ?? 0);
  return epley1rm(weightKg, effectiveReps);
}

/** The four dimensions a set can PR on — same labels as the backend `PRKind`. */
export type PRKind = 'weight' | 'e1rm' | 'reps_at_weight' | 'volume';

/**
 * A snapshot of a user's prior bests for one Exercise (normal sets only).
 *
 * Every field is "nothing logged yet" by default, so an empty `PriorBests` is a
 * clean slate. `repsByWeight` maps an exact weight to the most reps ever done at
 * it; a weight absent from it has never been lifted. Mirrors `PriorBests`.
 */
export interface PriorBests {
  bestWeightKg: number | null;
  bestE1rm: number | null;
  bestVolumeKg: number | null;
  repsByWeight: Map<number, number>;
}

/** A clean-slate PriorBests (no history). */
export function emptyPriorBests(): PriorBests {
  return {
    bestWeightKg: null,
    bestE1rm: null,
    bestVolumeKg: null,
    repsByWeight: new Map(),
  };
}

/** One PR a set achieved: the dimension, the new record value, and (for
 * reps-at-weight) the weight it happened at. Mirrors `PRResult`. */
export interface PRResult {
  kind: PRKind;
  value: number;
  atWeightKg: number | null;
}

/** True if `candidate` strictly improves on `prior` (null = no prior). */
function beats(candidate: number, prior: number | null): boolean {
  return prior == null || candidate > prior;
}

/** Whether a set of this type contributes to volume/PR stats (only `normal`).
 * Mirrors `services/volume.py` `counts_for_volume`. */
export function countsForPr(setType: SetType): boolean {
  return setType === 'normal';
}

export interface DetectPrsInput {
  weightKg: number;
  reps: number;
  setType: SetType;
  rir: number | null;
  prior: PriorBests;
}

/**
 * Return the PRs a just-logged set sets, given the user's prior bests.
 *
 * Empty when the set does not qualify (non-normal, zero load, or zero reps) or
 * beats nothing. Byte-for-byte the same logic as `detect_prs` in pr.py.
 */
export function detectPrs({
  weightKg,
  reps,
  setType,
  rir,
  prior,
}: DetectPrsInput): PRResult[] {
  // Non-normal sets never PR (the volume.py exclusion).
  if (!countsForPr(setType)) return [];
  // A zero-load or zero-rep set carries no signal.
  if (weightKg <= 0 || reps <= 0) return [];

  const results: PRResult[] = [];

  // 1. Best weight, at any rep count.
  if (beats(weightKg, prior.bestWeightKg)) {
    results.push({ kind: 'weight', value: weightKg, atWeightKg: null });
  }

  // 2. Best estimated 1RM (Effort-adjusted via RIR).
  const e1rm = estimated1rm(weightKg, reps, rir);
  if (beats(e1rm, prior.bestE1rm)) {
    results.push({ kind: 'e1rm', value: e1rm, atWeightKg: null });
  }

  // 3. Best reps at THIS exact weight (first ever at a weight always qualifies).
  const priorRepsHere = prior.repsByWeight.get(weightKg) ?? null;
  if (beats(reps, priorRepsHere)) {
    results.push({ kind: 'reps_at_weight', value: reps, atWeightKg: weightKg });
  }

  // 4. Best single-set volume load (weight × reps).
  const volume = weightKg * reps;
  if (beats(volume, prior.bestVolumeKg)) {
    results.push({ kind: 'volume', value: volume, atWeightKg: null });
  }

  return results;
}

/**
 * Build a PriorBests from a flat list of a user's prior NORMAL sets for one
 * Exercise (caller filters to the right exercise + normal type, and excludes the
 * candidate set). Mirrors the aggregation in `prior_bests_for` so the offline
 * detector sees the same history shape the backend computes.
 */
export function priorBestsFromSets(
  sets: { weightKg: number; reps: number; rir: number | null }[],
): PriorBests {
  const prior = emptyPriorBests();
  for (const s of sets) {
    if (s.weightKg <= 0 || s.reps <= 0) continue;
    if (prior.bestWeightKg == null || s.weightKg > prior.bestWeightKg) {
      prior.bestWeightKg = s.weightKg;
    }
    const volume = s.weightKg * s.reps;
    if (prior.bestVolumeKg == null || volume > prior.bestVolumeKg) {
      prior.bestVolumeKg = volume;
    }
    const e1rm = estimated1rm(s.weightKg, s.reps, s.rir);
    if (prior.bestE1rm == null || e1rm > prior.bestE1rm) {
      prior.bestE1rm = e1rm;
    }
    const priorReps = prior.repsByWeight.get(s.weightKg) ?? null;
    if (priorReps == null || s.reps > priorReps) {
      prior.repsByWeight.set(s.weightKg, s.reps);
    }
  }
  return prior;
}

/**
 * Human banner copy for a PR, mobile-first and non-blocking (CONTEXT.md: "New
 * 5-rep PR — 100 kg!"). One short phrase per dimension.
 */
export function prLabel(pr: PRResult): string {
  switch (pr.kind) {
    case 'weight':
      return `New weight PR — ${formatKg(pr.value)} kg!`;
    case 'e1rm':
      return `New estimated 1RM — ${formatKg(pr.value)} kg!`;
    case 'reps_at_weight':
      return `New ${pr.value}-rep PR — ${formatKg(pr.atWeightKg ?? 0)} kg!`;
    case 'volume':
      return `New volume PR — ${formatKg(pr.value)} kg!`;
  }
}

/** Trim a kg value to at most one decimal, dropping a trailing ".0". */
function formatKg(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}
