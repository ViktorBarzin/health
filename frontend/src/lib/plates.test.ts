import { describe, expect, it } from 'vitest';
import {
  closestLoadable,
  loadableWeights,
  platesPerSide,
  type PlateResult,
} from './plates';

// The plate calculator is a PURE client utility tapped live at the rack: given a
// target total weight, the bar, and the plate denominations the user owns, work
// out the per-side breakdown (greedy, largest-first) and — when the exact target
// isn't loadable from those plates — the closest weight that IS.
//
// Convention: `plates` are the denominations available, each assumed available
// in PAIRS (one per side). The breakdown is reported per side; the loaded total
// is `bar + 2 * sum(perSide)`.

const STD_PLATES = [1.25, 2.5, 5, 10, 15, 20, 25];
const BAR = 20;

function totalOf(bar: number, r: PlateResult): number {
  return bar + 2 * r.perSide.reduce((a, b) => a + b, 0);
}

describe('platesPerSide', () => {
  it('loads an exactly-achievable target greedily, largest-first', () => {
    // 100 kg on a 20 kg bar = 80 to split = 40/side = 25 + 15.
    const r = platesPerSide(100, { bar: BAR, plates: STD_PLATES });
    expect(r.exact).toBe(true);
    expect(r.total).toBe(100);
    expect(r.perSide).toEqual([25, 15]);
    expect(totalOf(BAR, r)).toBe(100);
  });

  it('returns an empty breakdown when the target equals the bar', () => {
    const r = platesPerSide(20, { bar: BAR, plates: STD_PLATES });
    expect(r.exact).toBe(true);
    expect(r.perSide).toEqual([]);
    expect(r.total).toBe(20);
  });

  it('uses the largest plates first and can repeat a denomination', () => {
    // 140 kg on 20 = 120 to split = 60/side = 25 + 25 + 10.
    const r = platesPerSide(140, { bar: BAR, plates: STD_PLATES });
    expect(r.exact).toBe(true);
    expect(r.perSide).toEqual([25, 25, 10]);
    expect(totalOf(BAR, r)).toBe(140);
  });

  it('rounds DOWN to the closest loadable weight when the exact target is impossible', () => {
    // 101 kg on 20 = 81 to split = 40.5/side; closest <= from {1.25..25} is 40
    // (25+15) → 100 total. The next loadable up is 102.5 (40.5+1.25 not possible
    // since 0.5 isn't a plate; 41.25/side → 102.5). closestLoadable picks the
    // nearest; ties go DOWN. 101 is nearer 100 (1) than 102.5 (1.5) → 100.
    const r = platesPerSide(101, { bar: BAR, plates: STD_PLATES });
    expect(r.exact).toBe(false);
    expect(r.total).toBe(100);
    expect(r.perSide).toEqual([25, 15]);
  });

  it('snaps UP when the closest loadable weight is above the target', () => {
    // 102 kg → loadable around it: 100 (diff 2) and 102.5 (diff 0.5). 102.5 wins.
    const r = platesPerSide(102, { bar: BAR, plates: STD_PLATES });
    expect(r.exact).toBe(false);
    expect(r.total).toBe(102.5);
    expect(totalOf(BAR, r)).toBe(102.5);
  });

  it('handles asymmetric leftovers: target below the smallest loadable increment', () => {
    // 21 kg on 20 = 1 to split = 0.5/side, but the smallest plate is 1.25.
    // 0.5 < 1.25 so nothing loads → closest is the bare bar (20) vs first step
    // (22.5). 21 is nearer 20 (1) than 22.5 (1.5) → bare bar.
    const r = platesPerSide(21, { bar: BAR, plates: STD_PLATES });
    expect(r.exact).toBe(false);
    expect(r.total).toBe(20);
    expect(r.perSide).toEqual([]);
  });

  it('clamps a target BELOW the bar weight to the bare bar', () => {
    const r = platesPerSide(10, { bar: BAR, plates: STD_PLATES });
    expect(r.exact).toBe(false);
    expect(r.total).toBe(20);
    expect(r.perSide).toEqual([]);
    expect(r.belowBar).toBe(true);
  });

  it('treats a target equal to the bar as exact, not below-bar', () => {
    const r = platesPerSide(20, { bar: BAR, plates: STD_PLATES });
    expect(r.belowBar).toBe(false);
    expect(r.exact).toBe(true);
  });

  it('with an EMPTY plate set, only the bare bar is achievable', () => {
    const r = platesPerSide(60, { bar: BAR, plates: [] });
    expect(r.exact).toBe(false);
    expect(r.total).toBe(20);
    expect(r.perSide).toEqual([]);
  });

  it('with an empty plate set and target == bar, it is exact', () => {
    const r = platesPerSide(20, { bar: BAR, plates: [] });
    expect(r.exact).toBe(true);
    expect(r.perSide).toEqual([]);
  });

  it('orders the per-side list largest-first regardless of input order', () => {
    const r = platesPerSide(50, { bar: BAR, plates: [5, 25, 1.25, 10, 2.5, 20, 15] });
    // 50 on 20 = 30 to split = 15/side = a single 15.
    expect(r.perSide).toEqual([15]);
  });

  it('handles a different bar weight (15 kg) correctly', () => {
    // 55 kg on 15 = 40 to split = 20/side = a single 20.
    const r = platesPerSide(55, { bar: 15, plates: STD_PLATES });
    expect(r.exact).toBe(true);
    expect(r.perSide).toEqual([20]);
    expect(totalOf(15, r)).toBe(55);
  });

  it('avoids floating-point drift on fractional plates (1.25 kg steps)', () => {
    // 22.5 on 20 = 2.5 to split = 1.25/side = a single 1.25.
    const r = platesPerSide(22.5, { bar: BAR, plates: STD_PLATES });
    expect(r.exact).toBe(true);
    expect(r.perSide).toEqual([1.25]);
    expect(r.total).toBeCloseTo(22.5, 9);
  });

  it('greedily approximates when a denomination is missing (no 15 kg plate)', () => {
    // Without a 15 kg plate, 40/side comes greedily from 25 + 10 + 5 = 40 exactly.
    const r = platesPerSide(100, { bar: BAR, plates: [2.5, 5, 10, 25] });
    expect(r.exact).toBe(true);
    expect(r.perSide).toEqual([25, 10, 5]);
    expect(totalOf(BAR, r)).toBe(100);
  });

  it('reports a CONSISTENT breakdown on a non-greedy-canonical plate set', () => {
    // Plates {15,20,25}, target 90kg → 35/side. Greedy grabs 25 first, then can
    // place nothing (10 left, no ≤10 plate) → greedy UNDERLOADS at 25. The
    // breakdown must instead realize 35 exactly (20 + 15), and perSide must sum
    // to (total - bar)/2 — never claim `exact` while loading less than `total`.
    const r = platesPerSide(90, { bar: BAR, plates: [15, 20, 25] });
    expect(r.exact).toBe(true);
    expect(r.total).toBe(90);
    // Whatever the breakdown, it MUST actually sum to the reported total.
    expect(BAR + 2 * r.perSide.reduce((a, b) => a + b, 0)).toBe(r.total);
    expect(r.perSide.reduce((a, b) => a + b, 0)).toBe(35);
  });

  it('never reports perSide that underloads the stated total (property)', () => {
    // Across odd plate sets and targets, the invariant total === bar + 2·Σ perSide
    // must always hold (the greedy-vs-subset-sum consistency bug).
    const sets = [
      [15, 20, 25],
      [3, 7],
      [2.5, 5, 10, 25],
      [1.25, 2.5, 5, 10, 15, 20, 25],
      [11, 13],
    ];
    for (const plates of sets) {
      for (let target = 20; target <= 160; target += 2.5) {
        const r = platesPerSide(target, { bar: BAR, plates });
        const loaded = BAR + 2 * r.perSide.reduce((a, b) => a + b, 0);
        expect(loaded).toBeCloseTo(r.total, 9);
      }
    }
  });
});

describe('loadableWeights', () => {
  it('starts at the bar and ascends in the smallest possible 2*plate steps', () => {
    const ws = loadableWeights({ bar: BAR, plates: [2.5, 5] }, 35);
    // per-side reachable sums from {2.5,5}: 0,2.5,5,7.5,10,12.5,... → totals
    // 20,25,30,35,40,45 within cap 35 → 20,25,30,35.
    expect(ws[0]).toBe(20);
    expect(ws).toContain(25);
    expect(ws).toContain(30);
    expect(ws).toContain(35);
    expect(ws.every((w) => w <= 35)).toBe(true);
    // strictly increasing, unique
    for (let i = 1; i < ws.length; i++) expect(ws[i]).toBeGreaterThan(ws[i - 1]);
  });

  it('is just the bar when there are no plates', () => {
    expect(loadableWeights({ bar: BAR, plates: [] }, 100)).toEqual([20]);
  });
});

describe('closestLoadable', () => {
  it('returns the exact weight when it is loadable', () => {
    expect(closestLoadable(100, { bar: BAR, plates: STD_PLATES })).toBe(100);
  });

  it('returns the nearest loadable weight, ties resolving downward', () => {
    // 101.25 is exactly between 100 and 102.5 → tie → DOWN → 100.
    expect(closestLoadable(101.25, { bar: BAR, plates: STD_PLATES })).toBe(100);
  });

  it('never returns below the bar', () => {
    expect(closestLoadable(5, { bar: BAR, plates: STD_PLATES })).toBe(20);
  });
});
