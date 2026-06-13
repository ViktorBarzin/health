import { describe, expect, it } from 'vitest';
import {
  MACRO_SERIES,
  entryMacros,
  formatMacro,
  formatServing,
  historyToSeries,
  macroCalorieSplit,
  type DiaryDaySummary,
} from './nutrition';

// Pure view-logic for the Nutrition UI: scaling a Food's per-serving macros by a
// quantity (the client-side mirror of the backend's entry_macros), formatting
// for display, the macronutrient calorie split for a ring/bar, and mapping the
// history endpoint to chart datapoints. No DOM, no fetch.

describe('entryMacros', () => {
  it('scales a Food per-serving macros by quantity', () => {
    // Chicken breast, 165/31/0/3.6 per 100 g serving, logged at 1.5 servings.
    const m = entryMacros(
      { calories: 165, protein_g: 31, carbs_g: 0, fat_g: 3.6 },
      1.5,
    );
    expect(m.calories).toBeCloseTo(247.5, 6);
    expect(m.protein_g).toBeCloseTo(46.5, 6);
    expect(m.carbs_g).toBeCloseTo(0, 6);
    expect(m.fat_g).toBeCloseTo(5.4, 6);
  });

  it('returns zeros for zero quantity', () => {
    const m = entryMacros({ calories: 200, protein_g: 10, carbs_g: 20, fat_g: 5 }, 0);
    expect(m).toEqual({ calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 });
  });
});

describe('formatMacro', () => {
  it('rounds calories to a whole number', () => {
    expect(formatMacro(247.5, 'calories')).toBe('248');
    expect(formatMacro(0, 'calories')).toBe('0');
  });

  it('shows one decimal with a g suffix for macronutrients', () => {
    expect(formatMacro(46.5, 'protein_g')).toBe('46.5 g');
    expect(formatMacro(5, 'fat_g')).toBe('5 g'); // trailing .0 trimmed
    expect(formatMacro(0, 'carbs_g')).toBe('0 g');
  });
});

describe('formatServing', () => {
  it('renders quantity × serving in the Food unit', () => {
    expect(formatServing(1.5, 100, 'g')).toBe('150 g');
    expect(formatServing(2, 1, 'egg')).toBe('2 egg');
    expect(formatServing(1, 1, 'medium')).toBe('1 medium');
  });

  it('trims trailing zeros on the computed amount', () => {
    expect(formatServing(0.5, 100, 'g')).toBe('50 g');
    expect(formatServing(1, 240, 'ml')).toBe('240 ml');
  });
});

describe('macroCalorieSplit', () => {
  it('splits calories across the three macros by Atwater factors', () => {
    // 30 P (120 kcal) + 40 C (160 kcal) + 10 F (90 kcal) = 370 kcal of macros.
    const split = macroCalorieSplit({ calories: 370, protein_g: 30, carbs_g: 40, fat_g: 10 });
    expect(split.protein.kcal).toBe(120);
    expect(split.carbs.kcal).toBe(160);
    expect(split.fat.kcal).toBe(90);
    // Percentages of the macro-calorie total.
    expect(split.protein.pct).toBeCloseTo(32.4, 1);
    expect(split.carbs.pct).toBeCloseTo(43.2, 1);
    expect(split.fat.pct).toBeCloseTo(24.3, 1);
  });

  it('is all-zero (no NaN) for an empty day', () => {
    const split = macroCalorieSplit({ calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 });
    for (const k of ['protein', 'carbs', 'fat'] as const) {
      expect(split[k].kcal).toBe(0);
      expect(split[k].pct).toBe(0);
    }
  });

  it('exposes a stable macro series for legends', () => {
    expect(MACRO_SERIES.map((s) => s.key)).toEqual(['protein', 'carbs', 'fat']);
  });
});

describe('historyToSeries', () => {
  const history: DiaryDaySummary[] = [
    { entry_date: '2026-06-11', total: { calories: 1800, protein_g: 120, carbs_g: 180, fat_g: 60 } },
    { entry_date: '2026-06-13', total: { calories: 2200, protein_g: 150, carbs_g: 220, fat_g: 70 } },
  ];

  it('maps a chosen metric to {time, value} datapoints for the chart', () => {
    const cals = historyToSeries(history, 'calories');
    expect(cals).toEqual([
      { time: '2026-06-11', value: 1800 },
      { time: '2026-06-13', value: 2200 },
    ]);
  });

  it('can select a macronutrient series', () => {
    const protein = historyToSeries(history, 'protein_g');
    expect(protein.map((p) => p.value)).toEqual([120, 150]);
  });

  it('returns an empty array for empty history', () => {
    expect(historyToSeries([], 'calories')).toEqual([]);
  });
});
