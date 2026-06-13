import { describe, expect, it } from 'vitest';
import type { ProgramMuscleVolume, ParamProvenance } from './types';
import {
  barHeightPct,
  evidenceGradeColor,
  evidenceGradeLabel,
  formatProvenanceRange,
  formatProvenanceValue,
  groupVolumeByMuscle,
  maxTargetSets,
  provenanceLabel,
  provenancePrincipleKeys,
  provenanceReceipts,
} from './program';

function vol(muscle: string, week: number, target_sets: number, is_deload = false): ProgramMuscleVolume {
  return { muscle, week, target_sets, is_deload };
}

describe('groupVolumeByMuscle', () => {
  it('groups rows by muscle, week-ordered, preserving first-seen muscle order', () => {
    const rows = [
      vol('chest', 2, 12),
      vol('lats', 1, 10),
      vol('chest', 1, 10),
      vol('lats', 2, 12),
    ];
    const grouped = groupVolumeByMuscle(rows);
    expect(grouped.map((g) => g.muscle)).toEqual(['chest', 'lats']);
    expect(grouped[0]?.weeks.map((w) => w.week)).toEqual([1, 2]);
    expect(grouped[1]?.weeks.map((w) => w.target_sets)).toEqual([10, 12]);
  });

  it('returns an empty list for no rows', () => {
    expect(groupVolumeByMuscle([])).toEqual([]);
  });
});

describe('maxTargetSets', () => {
  it('returns the largest target_sets', () => {
    expect(maxTargetSets([vol('chest', 1, 10), vol('chest', 2, 18)])).toBe(18);
  });

  it('is at least 1 for empty input (no divide-by-zero)', () => {
    expect(maxTargetSets([])).toBe(1);
  });
});

describe('barHeightPct', () => {
  it('scales to a percentage of the max', () => {
    expect(barHeightPct(10, 20)).toBe(50);
    expect(barHeightPct(20, 20)).toBe(100);
  });

  it('floors at 8% so a bar is always visible', () => {
    expect(barHeightPct(0, 20)).toBe(8);
    expect(barHeightPct(1, 100)).toBe(8);
  });

  it('handles a zero max defensively', () => {
    expect(barHeightPct(5, 0)).toBe(8);
  });
});

describe('provenanceLabel', () => {
  it('humanises snake_case parameter keys', () => {
    expect(provenanceLabel('weekly_sets_per_muscle_top')).toBe('weekly sets per muscle top');
    expect(provenanceLabel('rep_range_low')).toBe('rep range low');
  });

  it('renders a trailing _percent as a % sign', () => {
    expect(provenanceLabel('deload_volume_reduction_percent')).toBe(
      'deload volume reduction %',
    );
  });
});

describe('provenanceReceipts', () => {
  it('flattens a provenance map into labelled receipts', () => {
    const provenance: Record<string, ParamProvenance> = {
      effort_rir: { principle_key: 'effort-proximity-to-failure', value: 3, unit: 'RIR', min: 0, max: 3 },
      rep_range_low: { principle_key: 'rep-scheme', value: 6, unit: 'reps', min: null, max: null },
    };
    const receipts = provenanceReceipts(provenance);
    expect(receipts).toHaveLength(2);
    const effort = receipts.find((r) => r.param === 'effort_rir');
    expect(effort?.principle_key).toBe('effort-proximity-to-failure');
    expect(effort?.label).toBe('effort rir');
  });
});

describe('formatProvenanceValue', () => {
  it('appends the unit when present', () => {
    expect(
      formatProvenanceValue({ principle_key: 'k', value: 12, unit: 'sets', min: null, max: null }),
    ).toBe('12 sets');
  });

  it('omits the unit when absent', () => {
    expect(
      formatProvenanceValue({ principle_key: 'k', value: 6, unit: null, min: null, max: null }),
    ).toBe('6');
  });
});

describe('formatProvenanceRange', () => {
  it('renders a bounded range', () => {
    expect(
      formatProvenanceRange({ principle_key: 'k', value: 15, unit: 'sets', min: 10, max: 20 }),
    ).toBe('10–20 sets');
  });

  it('renders a min-only range with ≥', () => {
    expect(
      formatProvenanceRange({ principle_key: 'k', value: 2, unit: 'sessions', min: 2, max: null }),
    ).toBe('≥2 sessions');
  });

  it('falls back to the value when no bounds', () => {
    expect(
      formatProvenanceRange({ principle_key: 'k', value: 6, unit: 'reps', min: null, max: null }),
    ).toBe('6 reps');
  });
});

describe('provenancePrincipleKeys', () => {
  it('returns distinct principle keys in first-seen order', () => {
    const provenance: Record<string, ParamProvenance> = {
      weekly_sets_per_muscle_top: { principle_key: 'volume-dose-response', value: 20, unit: 'sets', min: 10, max: 20 },
      weekly_sets_per_muscle_start: { principle_key: 'volume-dose-response', value: 10, unit: 'sets', min: 10, max: 20 },
      effort_rir: { principle_key: 'effort-proximity-to-failure', value: 3, unit: 'RIR', min: 0, max: 3 },
    };
    expect(provenancePrincipleKeys(provenance)).toEqual([
      'volume-dose-response',
      'effort-proximity-to-failure',
    ]);
  });
});

describe('evidenceGrade', () => {
  it('labels each grade', () => {
    expect(evidenceGradeLabel('A')).toBe('Strong evidence');
    expect(evidenceGradeLabel('B')).toBe('Moderate evidence');
    expect(evidenceGradeLabel('C')).toBe('Limited evidence');
  });

  it('returns a distinct colour class per grade', () => {
    expect(evidenceGradeColor('A')).toContain('emerald');
    expect(evidenceGradeColor('B')).toContain('amber');
    expect(evidenceGradeColor('C')).toContain('orange');
  });
});
