// Pure view-logic for the Budget card (the Goal-driven daily target, #23).
//
// No DOM, no fetch — just the client-side helpers the nutrition page binds to:
// the macro target bundle off a Budget, "remaining" (target − logged, floored so
// the UI never shows a negative remaining), the Goal's human label, a weight-rate
// string, and a compact trend summary. Mirrors lib/nutrition.ts's discipline.
// Unit-tested in budget.test.ts.

import type { Budget, MacroTotals } from './types';

/** Human labels for the four Goals (CONTEXT.md "Goal"; the single Goal, ADR-0004). */
export const GOAL_LABELS = {
  bulk: 'Bulk',
  cut: 'Cut',
  maintain: 'Maintain',
  strength: 'Strength',
} as const;

export function goalLabel(goal: Budget['goal']): string {
  return GOAL_LABELS[goal] ?? goal;
}

/** A Budget's macro targets as a {calories,protein,carbs,fat} bundle (nulls→0). */
export function budgetMacroTargets(budget: Budget): MacroTotals {
  return {
    calories: budget.target_kcal ?? 0,
    protein_g: budget.protein_g ?? 0,
    carbs_g: budget.carbs_g ?? 0,
    fat_g: budget.fat_g ?? 0,
  };
}

/**
 * Remaining macros for the day = target − logged, **floored at zero** per macro
 * (a budget the user has met or exceeded shows 0 remaining, never a negative
 * number — overage is conveyed elsewhere, e.g. a full progress bar).
 */
export function remainingMacros(target: MacroTotals, logged: MacroTotals): MacroTotals {
  const rem = (t: number, l: number) => Math.max(0, t - l);
  return {
    calories: rem(target.calories, logged.calories),
    protein_g: rem(target.protein_g, logged.protein_g),
    carbs_g: rem(target.carbs_g, logged.carbs_g),
    fat_g: rem(target.fat_g, logged.fat_g),
  };
}

// Below this absolute weekly rate we call it "Holding" rather than showing a
// noisy ±0.0 — a trend slower than this is indistinguishable from maintenance.
const _RATE_HOLDING_THRESHOLD = 0.05;

/**
 * A weight-change rate (kg/week) as a compact human string: `"+0.3 kg/wk"`,
 * `"−0.5 kg/wk"` (true minus sign), `"Holding"` when within the dead-band, or
 * `""` for a null rate (no trend yet).
 */
export function formatRate(rateKgPerWeek: number | null): string {
  if (rateKgPerWeek === null) return '';
  if (Math.abs(rateKgPerWeek) < _RATE_HOLDING_THRESHOLD) return 'Holding';
  const sign = rateKgPerWeek > 0 ? '+' : '−';
  return `${sign}${Math.abs(rateKgPerWeek).toFixed(1)} kg/wk`;
}

/** A compact summary of the weight trend for the card. */
export interface TrendSummary {
  /** True when there's a de-noised current weight to show. */
  hasTrend: boolean;
  /** e.g. "82.4 kg", or "" when there's no trend. */
  weightLabel: string;
  /** e.g. "+0.3 kg/wk" / "Holding", or "" when there's no rate yet. */
  rateLabel: string;
}

/**
 * Summarise a Budget's weight trend into display strings. No de-noised weight
 * (insufficient data) ⇒ `hasTrend:false`; a weight but no rate (a single
 * weigh-in) ⇒ a weight label with an empty rate.
 */
export function trendSummary(budget: Budget): TrendSummary {
  const t = budget.trend;
  if (t.insufficient_data || t.true_weight_kg === null) {
    return { hasTrend: false, weightLabel: '', rateLabel: '' };
  }
  return {
    hasTrend: true,
    weightLabel: `${t.true_weight_kg.toFixed(1)} kg`,
    rateLabel: formatRate(t.rate_kg_per_week),
  };
}
