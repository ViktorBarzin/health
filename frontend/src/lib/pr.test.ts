import { describe, expect, it } from 'vitest';
import {
  detectPrs,
  emptyPriorBests,
  epley1rm,
  estimated1rm,
  prLabel,
  priorBestsFromSets,
  type PriorBests,
  type PRKind,
} from './pr';

// This suite mirrors the backend pure-core suites (tests/test_e1rm.py +
// tests/test_pr.py) case-for-case so the offline browser detector and the
// server provably agree. When you touch the formula or a rule, update both.

const WEIGHTS = [1, 20, 60, 100, 142.5, 315];
const REPS = [1, 2, 3, 5, 8, 12, 20];

function kinds(results: { kind: PRKind }[]): Set<PRKind> {
  return new Set(results.map((r) => r.kind));
}

function prior(overrides: Partial<PriorBests> = {}): PriorBests {
  return { ...emptyPriorBests(), ...overrides };
}

describe('epley1rm / estimated1rm', () => {
  it('returns the weight exactly at 1 rep', () => {
    for (const w of WEIGHTS) {
      expect(epley1rm(w, 1)).toBeCloseTo(w, 9);
      expect(estimated1rm(w, 1)).toBeCloseTo(w, 9);
    }
  });

  it('matches the 1-rep-anchored Epley known value (100×5)', () => {
    expect(epley1rm(100, 5)).toBeCloseTo(100 * (1 + 4 / 30), 9);
  });

  it('is non-decreasing in weight at fixed reps', () => {
    for (const reps of REPS) {
      let prev: number | null = null;
      for (const w of WEIGHTS) {
        const est = estimated1rm(w, reps);
        if (prev !== null) expect(est).toBeGreaterThanOrEqual(prev);
        prev = est;
      }
    }
  });

  it('is non-decreasing in reps at fixed weight', () => {
    for (const w of WEIGHTS) {
      let prev: number | null = null;
      for (const reps of REPS) {
        const est = estimated1rm(w, reps);
        if (prev !== null) expect(est).toBeGreaterThanOrEqual(prev);
        prev = est;
      }
    }
  });

  it('is zero for zero weight or zero reps', () => {
    expect(estimated1rm(0, 5)).toBe(0);
    expect(estimated1rm(100, 0)).toBe(0);
  });

  it('throws on negative inputs', () => {
    expect(() => estimated1rm(-1, 5)).toThrow();
    expect(() => estimated1rm(100, -1)).toThrow();
    expect(() => estimated1rm(100, 5, -1)).toThrow();
  });

  it('RIR adjustment never lowers the estimate and is monotonic in reserve', () => {
    for (const w of WEIGHTS) {
      const base = estimated1rm(w, 5);
      let prev: number | null = null;
      for (const rir of [0, 1, 2, 3, 4]) {
        const adj = estimated1rm(w, 5, rir);
        expect(adj).toBeGreaterThanOrEqual(base);
        if (prev !== null) expect(adj).toBeGreaterThanOrEqual(prev);
        prev = adj;
      }
    }
  });

  it('RIR 0 or null equals the unadjusted estimate', () => {
    for (const w of WEIGHTS) {
      for (const r of REPS) {
        expect(estimated1rm(w, r, 0)).toBeCloseTo(estimated1rm(w, r), 9);
        expect(estimated1rm(w, r, null)).toBeCloseTo(estimated1rm(w, r), 9);
      }
    }
  });

  it('reserve makes a set estimate like more reps to failure (100×5 @3 RIR == 100×8)', () => {
    expect(estimated1rm(100, 5, 3)).toBeCloseTo(estimated1rm(100, 8), 9);
  });
});

describe('detectPrs', () => {
  it('first-ever normal set is a PR on every dimension', () => {
    const r = detectPrs({
      weightKg: 100,
      reps: 5,
      setType: 'normal',
      rir: null,
      prior: emptyPriorBests(),
    });
    expect(kinds(r)).toEqual(
      new Set<PRKind>(['weight', 'e1rm', 'reps_at_weight', 'volume']),
    );
  });

  it('first-ever set carries its achieved values', () => {
    const r = detectPrs({
      weightKg: 100,
      reps: 5,
      setType: 'normal',
      rir: null,
      prior: emptyPriorBests(),
    });
    const byKind = new Map(r.map((p) => [p.kind, p]));
    expect(byKind.get('weight')!.value).toBeCloseTo(100, 9);
    expect(byKind.get('reps_at_weight')!.value).toBe(5);
    expect(byKind.get('reps_at_weight')!.atWeightKg).toBe(100);
    expect(byKind.get('volume')!.value).toBeCloseTo(500, 9);
    expect(byKind.get('e1rm')!.value).toBeCloseTo(100 * (1 + 4 / 30), 9);
  });

  it.each(['warmup', 'drop', 'failure'] as const)(
    'never PRs for a %s set even against empty history',
    (setType) => {
      const r = detectPrs({
        weightKg: 500,
        reps: 20,
        setType,
        rir: null,
        prior: emptyPriorBests(),
      });
      expect(r).toEqual([]);
    },
  );

  it('heavier weight is a weight PR; equal/lighter is not', () => {
    const p = prior({ bestWeightKg: 100, bestE1rm: 200, bestVolumeKg: 2000 });
    expect(
      kinds(detectPrs({ weightKg: 102.5, reps: 1, setType: 'normal', rir: null, prior: p })),
    ).toContain('weight');
    expect(
      kinds(detectPrs({ weightKg: 100, reps: 1, setType: 'normal', rir: null, prior: p })),
    ).not.toContain('weight');
    expect(
      kinds(detectPrs({ weightKg: 80, reps: 1, setType: 'normal', rir: null, prior: p })),
    ).not.toContain('weight');
  });

  it('higher e1RM is an e1RM PR; equal is not', () => {
    const p = prior({ bestWeightKg: 200, bestE1rm: 110, bestVolumeKg: 99999 });
    expect(
      kinds(detectPrs({ weightKg: 100, reps: 5, setType: 'normal', rir: null, prior: p })),
    ).toContain('e1rm');
    const exact = 100 * (1 + 4 / 30);
    const p2 = prior({ bestE1rm: exact, bestWeightKg: 999, bestVolumeKg: 999999 });
    expect(
      kinds(detectPrs({ weightKg: 100, reps: 5, setType: 'normal', rir: null, prior: p2 })),
    ).not.toContain('e1rm');
  });

  it('reps in reserve can tip an e1RM PR', () => {
    const p = prior({ bestE1rm: 116, bestWeightKg: 999, bestVolumeKg: 999999 });
    expect(
      kinds(detectPrs({ weightKg: 100, reps: 5, setType: 'normal', rir: 0, prior: p })),
    ).not.toContain('e1rm');
    expect(
      kinds(detectPrs({ weightKg: 100, reps: 5, setType: 'normal', rir: 3, prior: p })),
    ).toContain('e1rm');
  });

  it('more reps at a known weight is a reps PR; equal is not; new weight always is', () => {
    const p = prior({
      bestWeightKg: 100,
      bestE1rm: 500,
      bestVolumeKg: 999999,
      repsByWeight: new Map([[100, 5]]),
    });
    expect(
      kinds(detectPrs({ weightKg: 100, reps: 6, setType: 'normal', rir: null, prior: p })),
    ).toContain('reps_at_weight');
    expect(
      kinds(detectPrs({ weightKg: 100, reps: 5, setType: 'normal', rir: null, prior: p })),
    ).not.toContain('reps_at_weight');
    // 110 kg never lifted → reps PR even with fewer reps.
    expect(
      kinds(detectPrs({ weightKg: 110, reps: 2, setType: 'normal', rir: null, prior: p })),
    ).toContain('reps_at_weight');
  });

  it('higher single-set volume is a volume PR; equal is not', () => {
    const p = prior({ bestWeightKg: 999, bestE1rm: 99999, bestVolumeKg: 500 });
    expect(
      kinds(detectPrs({ weightKg: 80, reps: 8, setType: 'normal', rir: null, prior: p })),
    ).toContain('volume');
    expect(
      kinds(detectPrs({ weightKg: 100, reps: 5, setType: 'normal', rir: null, prior: p })),
    ).not.toContain('volume');
  });

  it('one set can fire several PRs at once', () => {
    const p = prior({
      bestWeightKg: 90,
      bestE1rm: 100,
      bestVolumeKg: 400,
      repsByWeight: new Map([[90, 5]]),
    });
    expect(
      kinds(detectPrs({ weightKg: 100, reps: 6, setType: 'normal', rir: null, prior: p })),
    ).toEqual(new Set<PRKind>(['weight', 'e1rm', 'reps_at_weight', 'volume']));
  });

  it('zero weight or zero reps never PRs', () => {
    expect(
      detectPrs({ weightKg: 0, reps: 10, setType: 'normal', rir: null, prior: emptyPriorBests() }),
    ).toEqual([]);
    expect(
      detectPrs({ weightKg: 100, reps: 0, setType: 'normal', rir: null, prior: emptyPriorBests() }),
    ).toEqual([]);
  });
});

describe('priorBestsFromSets', () => {
  it('aggregates only the supplied sets (caller filters normal/exercise/exclude)', () => {
    const prior = priorBestsFromSets([
      { weightKg: 100, reps: 5, rir: null },
      { weightKg: 120, reps: 3, rir: null },
    ]);
    expect(prior.bestWeightKg).toBeCloseTo(120, 9);
    expect(prior.bestVolumeKg).toBeCloseTo(500, 9); // 100×5 > 120×3
    expect(prior.repsByWeight.get(100)).toBe(5);
    expect(prior.repsByWeight.get(120)).toBe(3);
  });
});

describe('prLabel', () => {
  it('phrases a rep PR with its weight', () => {
    expect(prLabel({ kind: 'reps_at_weight', value: 5, atWeightKg: 100 })).toBe(
      'New 5-rep PR — 100 kg!',
    );
  });

  it('drops a trailing .0 on whole-kg values', () => {
    expect(prLabel({ kind: 'weight', value: 102.5, atWeightKg: null })).toBe(
      'New weight PR — 102.5 kg!',
    );
    expect(prLabel({ kind: 'weight', value: 100, atWeightKg: null })).toBe(
      'New weight PR — 100 kg!',
    );
  });
});
