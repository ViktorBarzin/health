import { describe, expect, it } from 'vitest';
import { warmupRamp, type WarmupSet } from './warmup';
import type { GymEquipment } from './plates';

// The warm-up calculator is a PURE client utility: given a working weight (and
// optionally working reps), suggest a sensible warm-up ramp — an empty-bar set
// then a few ascending percentage sets — each ROUNDED to a weight actually
// loadable from the user's bar + plates (it delegates to the plate calculator).

const STD: GymEquipment = { bar: 20, plates: [1.25, 2.5, 5, 10, 15, 20, 25] };

function weights(ramp: WarmupSet[]): number[] {
  return ramp.map((s) => s.weight);
}

describe('warmupRamp', () => {
  it('starts at the empty bar and ascends to (but excludes) the working weight', () => {
    const ramp = warmupRamp(100, { equipment: STD });
    expect(ramp.length).toBeGreaterThan(0);
    expect(ramp[0].weight).toBe(20); // empty bar first
    // strictly ascending
    for (let i = 1; i < ramp.length; i++) {
      expect(ramp[i].weight).toBeGreaterThan(ramp[i - 1].weight);
    }
    // never reaches or exceeds the working weight (warm-ups are sub-working)
    expect(ramp[ramp.length - 1].weight).toBeLessThan(100);
  });

  it('rounds every warm-up weight to a loadable weight on the given equipment', () => {
    const ramp = warmupRamp(100, { equipment: STD });
    for (const s of ramp) {
      // each weight must be the bar + an even pair of available plates
      const overBar = s.weight - STD.bar;
      expect(overBar % 1.25).toBeCloseTo(0, 9); // multiples of the smallest plate pair root
      expect(s.weight).toBeGreaterThanOrEqual(STD.bar);
    }
  });

  it('uses the default 40/60/80% ramp anchored on the working weight', () => {
    // 100 kg working → ~40/60/80 = 40/60/80, all loadable on STD → bar + those.
    const ws = weights(warmupRamp(100, { equipment: STD }));
    expect(ws).toContain(20); // empty bar
    expect(ws).toContain(40);
    expect(ws).toContain(60);
    expect(ws).toContain(80);
  });

  it('collapses duplicate/again-the-bar percentage rungs into distinct weights', () => {
    // Light working weight: percentages round near the bar; the ramp must not
    // repeat the same loadable weight twice.
    const ws = weights(warmupRamp(30, { equipment: STD }));
    expect(new Set(ws).size).toBe(ws.length);
  });

  it('returns just the empty bar when the working weight is AT the bar', () => {
    const ramp = warmupRamp(20, { equipment: STD });
    expect(weights(ramp)).toEqual([20]);
  });

  it('returns just the empty bar when the working weight is BELOW the bar', () => {
    const ramp = warmupRamp(10, { equipment: STD });
    expect(weights(ramp)).toEqual([20]);
  });

  it('suggests descending reps as the load climbs (fewer reps when heavier)', () => {
    const ramp = warmupRamp(100, { equipment: STD, workingReps: 5 });
    // reps are non-increasing across the ramp and each is >= 1
    for (let i = 1; i < ramp.length; i++) {
      expect(ramp[i].reps).toBeLessThanOrEqual(ramp[i - 1].reps);
      expect(ramp[i].reps).toBeGreaterThanOrEqual(1);
    }
    // first (empty bar) warm-up uses the most reps
    expect(ramp[0].reps).toBeGreaterThanOrEqual(ramp[ramp.length - 1].reps);
  });

  it('omits a percentage rung that would round to the empty bar (no duplicate of set 1)', () => {
    // 50 kg working: 40% = 20 == bar. The 40% rung must not duplicate the empty
    // bar; the ramp stays unique and ascending.
    const ws = weights(warmupRamp(50, { equipment: STD }));
    expect(ws[0]).toBe(20);
    expect(new Set(ws).size).toBe(ws.length);
    expect(ws.every((w) => w < 50)).toBe(true);
  });

  it('still produces a bar-only ramp when there are no plates and weight > bar', () => {
    // Nothing loads, so every percentage rounds to the bar; the result is just
    // the single empty-bar set (deduped).
    const ramp = warmupRamp(60, { equipment: { bar: 20, plates: [] } });
    expect(weights(ramp)).toEqual([20]);
  });

  it('accepts a custom percentage ramp', () => {
    const ws = weights(
      warmupRamp(100, { equipment: STD, percentages: [0.5, 0.75] }),
    );
    expect(ws).toContain(20); // always the empty bar first
    expect(ws).toContain(50);
    expect(ws).toContain(75);
  });
});
