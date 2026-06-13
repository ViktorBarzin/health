import { describe, expect, it } from 'vitest';
import {
  GOAL_LABELS,
  budgetMacroTargets,
  formatRate,
  goalLabel,
  remainingMacros,
  trendSummary,
} from './budget';
import type { Budget, MacroTotals } from './types';

// Pure view-logic for the Budget card (#23): "remaining" = target − logged
// (floored for display), the goal label, a human weight-rate string, and a
// trend summary. No DOM, no fetch — mirrors lib/nutrition.ts's discipline.

function macros(
  calories: number,
  protein_g: number,
  carbs_g: number,
  fat_g: number,
): MacroTotals {
  return { calories, protein_g, carbs_g, fat_g };
}

describe('remainingMacros', () => {
  it('subtracts logged from target per macro', () => {
    const r = remainingMacros(macros(2500, 180, 250, 70), macros(1800, 120, 150, 50));
    expect(r.calories).toBe(700);
    expect(r.protein_g).toBe(60);
    expect(r.carbs_g).toBe(100);
    expect(r.fat_g).toBe(20);
  });

  it('floors at zero when logged exceeds target (no negative "remaining")', () => {
    const r = remainingMacros(macros(2000, 150, 200, 60), macros(2400, 170, 260, 80));
    expect(r.calories).toBe(0);
    expect(r.protein_g).toBe(0);
    expect(r.carbs_g).toBe(0);
    expect(r.fat_g).toBe(0);
  });

  it('treats exactly-met as zero remaining', () => {
    const r = remainingMacros(macros(2000, 150, 200, 60), macros(2000, 150, 200, 60));
    expect(r.calories).toBe(0);
  });
});

describe('budgetMacroTargets', () => {
  it('pulls the macro target bundle off a Budget', () => {
    const budget = {
      target_kcal: 2500,
      protein_g: 180,
      carbs_g: 250,
      fat_g: 70,
    } as Budget;
    const t = budgetMacroTargets(budget);
    expect(t).toEqual(macros(2500, 180, 250, 70));
  });

  it('coerces nulls to zero (insufficient-data Budget)', () => {
    const budget = {
      target_kcal: null,
      protein_g: null,
      carbs_g: null,
      fat_g: null,
    } as Budget;
    expect(budgetMacroTargets(budget)).toEqual(macros(0, 0, 0, 0));
  });
});

describe('goalLabel', () => {
  it('maps every Goal to a human label', () => {
    expect(goalLabel('bulk')).toBe(GOAL_LABELS.bulk);
    expect(goalLabel('cut')).toBe(GOAL_LABELS.cut);
    expect(goalLabel('maintain')).toBe(GOAL_LABELS.maintain);
    expect(goalLabel('strength')).toBe(GOAL_LABELS.strength);
  });
});

describe('formatRate', () => {
  it('shows a gain with a + sign and kg/wk', () => {
    expect(formatRate(0.31)).toBe('+0.3 kg/wk');
  });

  it('shows a loss with a − sign', () => {
    expect(formatRate(-0.52)).toBe('−0.5 kg/wk');
  });

  it('shows a near-zero rate as Holding', () => {
    expect(formatRate(0.02)).toBe('Holding');
    expect(formatRate(-0.03)).toBe('Holding');
  });

  it('is empty for a null rate', () => {
    expect(formatRate(null)).toBe('');
  });
});

describe('trendSummary', () => {
  it('summarises a measured trend with weight + rate', () => {
    const budget = {
      trend: {
        insufficient_data: false,
        true_weight_kg: 82.4,
        rate_kg_per_week: 0.31,
        rate_pct_per_week: 0.38,
        n_samples: 20,
      },
    } as Budget;
    const s = trendSummary(budget);
    expect(s.hasTrend).toBe(true);
    expect(s.weightLabel).toBe('82.4 kg');
    expect(s.rateLabel).toBe('+0.3 kg/wk');
  });

  it('reports no trend when the trend is insufficient', () => {
    const budget = {
      trend: {
        insufficient_data: true,
        true_weight_kg: null,
        rate_kg_per_week: null,
        rate_pct_per_week: null,
        n_samples: 0,
      },
    } as Budget;
    const s = trendSummary(budget);
    expect(s.hasTrend).toBe(false);
    expect(s.weightLabel).toBe('');
  });

  it('shows a current weight but no rate when only a single weigh-in exists', () => {
    const budget = {
      trend: {
        insufficient_data: false,
        true_weight_kg: 80.0,
        rate_kg_per_week: null,
        rate_pct_per_week: null,
        n_samples: 1,
      },
    } as Budget;
    const s = trendSummary(budget);
    expect(s.hasTrend).toBe(true);
    expect(s.weightLabel).toBe('80.0 kg');
    expect(s.rateLabel).toBe('');
  });
});
