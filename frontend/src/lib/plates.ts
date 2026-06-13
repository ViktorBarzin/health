// Plate calculator — a PURE client utility tapped live at the rack.
//
// Given a target total weight, the bar, and the plate denominations the user
// owns (their Gym Profile), it works out the per-side breakdown loaded
// greedily largest-first, and — when the exact target isn't loadable — the
// closest weight that IS. Pure and importable: no DOM, no network, no clock.
//
// Convention: `plates` lists the *denominations* the user owns, each assumed
// available in PAIRS (one per side — a barbell is loaded symmetrically). The
// breakdown is reported PER SIDE; the loaded total is `bar + 2 * sum(perSide)`.

/** A user's loading equipment: their bar weight and owned plate denominations. */
export interface GymEquipment {
  /** Weight of the bar in kg (e.g. 20). */
  bar: number;
  /** Plate denominations owned, in kg (e.g. [1.25, 2.5, 5, 10, 15, 20, 25]). */
  plates: number[];
}

/** The plate breakdown for a target weight on a given bar + plate set. */
export interface PlateResult {
  /** Whether {@link total} equals the requested target exactly. */
  exact: boolean;
  /** The achievable total this breakdown loads (kg). */
  total: number;
  /** Plates loaded on EACH side, largest-first (kg). Empty = bare bar. */
  perSide: number[];
  /** True when the requested target was below the bar weight (clamped to bar). */
  belowBar: boolean;
}

// Gym weights come in 0.25 kg granularity at finest; work in integer
// hundredths of a kg internally so 1.25-kg plate arithmetic never drifts.
const SCALE = 100;
const toI = (kg: number): number => Math.round(kg * SCALE);
const fromI = (i: number): number => i / SCALE;

/**
 * Greedy largest-first per-side breakdown for a target total.
 *
 * If the exact target can't be made from the available plates, the result is
 * the CLOSEST loadable weight (ties resolve downward) and `exact` is false. A
 * target at or below the bar yields the bare bar.
 */
export function platesPerSide(
  targetKg: number,
  { bar, plates }: GymEquipment,
): PlateResult {
  const barI = toI(bar);
  const targetI = toI(targetKg);

  if (targetI <= barI) {
    return {
      exact: targetI === barI,
      total: bar,
      perSide: [],
      belowBar: targetI < barI,
    };
  }

  // Enumerate every loadable per-side sum together with a concrete plate
  // breakdown that realizes it, then pick the sum whose total is nearest the
  // target (ties downward). Reporting the recorded breakdown (not a re-derived
  // greedy one) keeps `perSide` summing to exactly (total - bar) / 2 even when
  // the plate set isn't greedy-canonical — the bug a greedy re-decompose hits.
  const wantPerSide = (targetI - barI) / 2;
  const reachable = reachablePerSide(plates, searchCapI(wantPerSide, plates));

  let bestSum = 0; // the bare bar (per-side 0) is always achievable
  let bestDist = Math.abs(targetI - barI);
  for (const sum of reachable.keys()) {
    const total = barI + 2 * sum;
    const dist = Math.abs(targetI - total);
    // Strictly-less wins; on a tie prefer the LOWER total (don't overshoot).
    if (dist < bestDist || (dist === bestDist && total < barI + 2 * bestSum)) {
      bestSum = sum;
      bestDist = dist;
    }
  }
  const totalI = barI + 2 * bestSum;
  return {
    exact: totalI === targetI,
    total: fromI(totalI),
    perSide: breakdownFor(bestSum, plates, reachable).map(fromI),
    belowBar: false,
  };
}

/**
 * The list of every loadable total weight from the bar up to `capKg`,
 * ascending and unique. Just the bar when no plates are available.
 */
export function loadableWeights(
  { bar, plates }: GymEquipment,
  capKg: number,
): number[] {
  const barI = toI(bar);
  const capI = toI(capKg);
  const reachable = reachablePerSide(plates, Math.max(0, (capI - barI) / 2));
  const totals = new Set<number>([barI]); // the bare bar is always loadable
  for (const sum of reachable.keys()) {
    const total = barI + 2 * sum;
    if (total <= capI) totals.add(total);
  }
  return [...totals]
    .filter((t) => t <= capI)
    .sort((a, b) => a - b)
    .map(fromI);
}

/**
 * The loadable total weight nearest to `targetKg` (ties resolve downward),
 * never below the bar.
 */
export function closestLoadable(targetKg: number, eq: GymEquipment): number {
  return platesPerSide(targetKg, eq).total;
}

// --- internals (integer-hundredths space) ---

/**
 * The plate breakdown (integer hundredths, largest-first) for an achievable
 * per-side `sumI`. Prefers the GREEDY largest-first decomposition — the natural
 * "grab the heaviest plates that fit" a lifter does and what the tests pin — but
 * falls back to the subset-sum-recorded breakdown when greedy can't hit the sum
 * exactly (a non-canonical plate set, e.g. {15,20,25} reaching 35 as 20+15).
 */
function breakdownFor(
  sumI: number,
  plates: number[],
  reachable: Map<number, number[]>,
): number[] {
  let remaining = sumI;
  const desc = [...new Set(plates.map(toI).filter((p) => p > 0))].sort(
    (a, b) => b - a,
  );
  const greedy: number[] = [];
  for (const p of desc) {
    while (remaining >= p) {
      greedy.push(p);
      remaining -= p;
    }
  }
  // Greedy nailed it → use it; otherwise trust the recorded subset-sum breakdown.
  return remaining === 0 ? greedy : (reachable.get(sumI) ?? []);
}

/**
 * How far (per side, integer hundredths) the reachable-sum search must run to be
 * sure the closest loadable weight to `wantPerSideI` is found: the wanted load
 * plus one of the largest plate, so the next rung *above* the target is included.
 */
function searchCapI(wantPerSideI: number, plates: number[]): number {
  const maxPlateI = plates.length
    ? Math.max(0, ...plates.map(toI).filter((p) => p > 0))
    : 0;
  return Math.max(0, wantPerSideI) + maxPlateI;
}

/**
 * Map every reachable per-side plate sum (integer hundredths, up to `capI`) to a
 * concrete plate breakdown that realizes it — each denomination available in
 * unlimited supply per side. Unbounded subset-sum; the cap keeps it bounded.
 *
 * Crucially this returns the actual multiset for each sum (largest-first), so a
 * caller never has to re-derive the breakdown greedily — which would underload
 * on a non-canonical plate set (e.g. {15,20,25} reaching 35 as 20+15, not 25).
 * Always includes the empty breakdown for 0 (the bare bar).
 */
function reachablePerSide(
  plates: number[],
  capPerSideI: number,
): Map<number, number[]> {
  const capI = Math.max(0, Math.round(capPerSideI));
  // Largest-first so each breakdown lists heavier plates first (loading order).
  const denomsI = [...new Set(plates.map(toI).filter((p) => p > 0))].sort(
    (a, b) => b - a,
  );
  // Breakdowns are stored in integer hundredths (the caller maps to kg once).
  const best = new Map<number, number[]>([[0, []]]);
  // Add denominations largest-first; for each, compound its multiples onto the
  // sums reachable so far (unbounded knapsack). First breakdown found for a sum
  // wins — and because we go largest-first, that's the fewest-plates one.
  for (const d of denomsI) {
    for (const [base, plate_list] of [...best]) {
      let v = base + d;
      const list = [...plate_list];
      while (v <= capI) {
        list.push(d);
        if (!best.has(v)) best.set(v, [...list]);
        v += d;
      }
    }
  }
  return best;
}
