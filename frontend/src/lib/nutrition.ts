// Pure view-logic for the Nutrition UI (the MyFitnessPal core, #21).
//
// No DOM, no fetch — just the client-side helpers the diary pages bind to:
// scaling a Food's per-serving macros by a quantity (a mirror of the backend's
// services.nutrition.entry_macros), display formatting, the macronutrient
// calorie split for a breakdown bar, and mapping the history endpoint to the
// {time, value} datapoints the existing chart components expect. Unit-tested in
// nutrition.test.ts.

import type { MacroTotals } from './types';

/** A Food's per-serving macros (the subset entryMacros needs). */
export interface PerServingMacros {
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
}

/** Which macro field a formatter/series is operating on. */
export type MacroKey = 'calories' | 'protein_g' | 'carbs_g' | 'fat_g';

// Atwater factors: kcal per gram of each macronutrient.
const KCAL_PER_G = { protein_g: 4, carbs_g: 4, fat_g: 9 } as const;

/**
 * Scale a Food's per-serving macros by `quantity` (number of servings) — the
 * client-side mirror of the backend's per-entry contribution. Unrounded; the
 * caller formats for display.
 */
export function entryMacros(food: PerServingMacros, quantity: number): MacroTotals {
  return {
    calories: food.calories * quantity,
    protein_g: food.protein_g * quantity,
    carbs_g: food.carbs_g * quantity,
    fat_g: food.fat_g * quantity,
  };
}

/** Trim a trailing `.0` from a fixed(1) string (so "5.0" → "5", "5.4" stays). */
function trim1(n: number): string {
  return n.toFixed(1).replace(/\.0$/, '');
}

/**
 * Format a macro value for display: calories as a whole number, the three
 * macronutrients to one decimal (trailing .0 trimmed) with a "g" suffix.
 */
export function formatMacro(value: number, key: MacroKey): string {
  if (key === 'calories') return Math.round(value).toString();
  return `${trim1(value)} g`;
}

/**
 * Render an entry's amount as `quantity × serving_size` in the Food's unit —
 * e.g. 1.5 servings of a 100 g Food → "150 g", 2 servings of "1 egg" → "2 egg".
 */
export function formatServing(
  quantity: number,
  servingSize: number,
  servingUnit: string,
): string {
  return `${trim1(quantity * servingSize)} ${servingUnit}`;
}

/** One macronutrient's contribution to the day's macro-calories. */
export interface MacroSlice {
  kcal: number;
  pct: number;
}

export interface MacroCalorieSplit {
  protein: MacroSlice;
  carbs: MacroSlice;
  fat: MacroSlice;
}

/** Stable order + display metadata for the three macros (legend, bar colours). */
export const MACRO_SERIES = [
  { key: 'protein', label: 'Protein', field: 'protein_g', color: '#60a5fa' },
  { key: 'carbs', label: 'Carbs', field: 'carbs_g', color: '#34d399' },
  { key: 'fat', label: 'Fat', field: 'fat_g', color: '#fbbf24' },
] as const;

/**
 * Split a macro bundle into each macronutrient's calorie contribution (grams ×
 * Atwater factor) and its percentage of the macro-calorie total. Percentages use
 * the macro-calorie sum (not the stated `calories`) so the three always add to
 * 100% for a breakdown bar; an empty day is all zeros (no NaN).
 */
export function macroCalorieSplit(totals: MacroTotals): MacroCalorieSplit {
  const p = totals.protein_g * KCAL_PER_G.protein_g;
  const c = totals.carbs_g * KCAL_PER_G.carbs_g;
  const f = totals.fat_g * KCAL_PER_G.fat_g;
  const sum = p + c + f;
  const pct = (x: number) => (sum > 0 ? (x / sum) * 100 : 0);
  return {
    protein: { kcal: p, pct: pct(p) },
    carbs: { kcal: c, pct: pct(c) },
    fat: { kcal: f, pct: pct(f) },
  };
}

/** One day's totals as returned by GET /api/nutrition/history. */
export interface DiaryDaySummary {
  entry_date: string;
  total: MacroTotals;
}

/** A {time, value} datapoint, the shape BarChart/TimeSeriesChart consume. */
export interface SeriesPoint {
  time: string;
  value: number;
}

/**
 * Map the history endpoint's per-day totals to chart datapoints for one metric
 * (calories or a macronutrient), in date order.
 */
export function historyToSeries(
  history: DiaryDaySummary[],
  key: MacroKey,
): SeriesPoint[] {
  return history.map((d) => ({ time: d.entry_date, value: d.total[key] }));
}
