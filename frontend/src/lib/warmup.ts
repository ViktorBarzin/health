// Warm-up calculator — a PURE client utility, built on the plate calculator.
//
// Given a working weight (and optionally working reps), it suggests a sensible
// warm-up ramp: an empty-bar set, then a few ascending percentage sets, each
// ROUNDED to a weight actually loadable from the user's bar + plates. The ramp
// is sub-working (warm-ups never reach the work set) and de-duplicated, so a
// light working weight that rounds several rungs onto the bare bar collapses to
// a single set rather than repeating the same weight.

import { closestLoadable, type GymEquipment } from './plates';

/** One warm-up set: a loadable weight and a suggested rep count. */
export interface WarmupSet {
  weight: number;
  reps: number;
}

export interface WarmupOptions {
  equipment: GymEquipment;
  /**
   * Fractions of the working weight for the ramp rungs, ascending. Defaults to
   * a conventional 40/60/80 % ramp; the empty bar is always prepended.
   */
  percentages?: number[];
  /** The working set's reps; used to scale the warm-up rep suggestions down. */
  workingReps?: number;
}

const DEFAULT_PERCENTAGES = [0.4, 0.6, 0.8];

/**
 * Build the warm-up ramp for a working weight.
 *
 * Always starts with the empty bar. Each percentage rung is rounded to the
 * nearest loadable weight; rungs that round to a weight already in the ramp, to
 * the bar, or to >= the working weight are dropped. Reps descend as load climbs.
 */
export function warmupRamp(
  workingKg: number,
  { equipment, percentages = DEFAULT_PERCENTAGES, workingReps = 8 }: WarmupOptions,
): WarmupSet[] {
  const bar = equipment.bar;

  // At or below the bar there's nothing to warm up to — just the empty bar.
  if (workingKg <= bar) {
    return [{ weight: bar, reps: warmupReps(0, workingReps) }];
  }

  // Candidate loadable weights: the empty bar, then each percentage rung snapped
  // to a loadable weight. Keep only strictly-ascending, sub-working, unique ones.
  const rungs: number[] = [bar];
  const sorted = [...percentages].filter((p) => p > 0 && p < 1).sort((a, b) => a - b);
  for (const p of sorted) {
    const snapped = closestLoadable(workingKg * p, equipment);
    if (snapped <= rungs[rungs.length - 1]) continue; // not strictly higher
    if (snapped >= workingKg) continue; // a warm-up is below the work set
    rungs.push(snapped);
  }

  return rungs.map((weight, i) => ({
    weight,
    // Fraction of the way up the ramp, 0 at the empty bar → ~1 at the top rung.
    reps: warmupReps(rungs.length > 1 ? i / (rungs.length - 1) : 0, workingReps),
  }));
}

/**
 * Suggested warm-up reps for a rung, given how far up the ramp it is (0..1) and
 * the working reps. Warm-ups start higher-rep (prime the movement) and taper to
 * around the working reps as the load approaches it; never below 1.
 */
function warmupReps(fractionUp: number, workingReps: number): number {
  // Empty bar ~ working+5 reps, top rung ~ working reps. Linear taper, floored.
  const top = Math.max(1, workingReps);
  const base = top + 5;
  const reps = Math.round(base - fractionUp * (base - top));
  return Math.max(1, reps);
}
