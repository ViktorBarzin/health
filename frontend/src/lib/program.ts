// Pure helpers for the Program overview UI (#13, ADR-0004).
//
// Generation itself is server-side and deterministic (the backend composes a
// Program from the Principles KB); the frontend only *renders* a Program. These
// are the small, pure view transforms the overview needs — extracted here so they
// are unit-testable in isolation (vitest) rather than buried in the .svelte file.

import type { ProgramMuscleVolume, ParamProvenance } from './types';

/** A muscle's weekly volume series, in week order, for the ramp strips. */
export interface ProgramMuscleVolumeSeries {
  muscle: string;
  weeks: ProgramMuscleVolume[];
}

/**
 * Group volume rows by muscle into week-ordered series, preserving first-seen
 * muscle order (stable across renders). Each series is sorted ascending by week.
 */
export function groupVolumeByMuscle(rows: ProgramMuscleVolume[]): ProgramMuscleVolumeSeries[] {
  const order: string[] = [];
  const byMuscle = new Map<string, ProgramMuscleVolume[]>();
  for (const row of rows) {
    if (!byMuscle.has(row.muscle)) {
      byMuscle.set(row.muscle, []);
      order.push(row.muscle);
    }
    byMuscle.get(row.muscle)!.push(row);
  }
  return order.map((muscle) => ({
    muscle,
    weeks: [...byMuscle.get(muscle)!].sort((a, b) => a.week - b.week),
  }));
}

/** The largest target_sets across all rows (>= 1), for scaling the bar heights. */
export function maxTargetSets(rows: ProgramMuscleVolume[]): number {
  return Math.max(1, ...rows.map((r) => r.target_sets));
}

/** Bar height as a percentage of the tallest, floored so a bar is always visible. */
export function barHeightPct(targetSets: number, maxSets: number): number {
  if (maxSets <= 0) return 8;
  return Math.max(8, Math.round((targetSets / maxSets) * 100));
}

/** A provenance entry flattened with its parameter name, for the receipts list. */
export interface ProvenanceReceipt extends ParamProvenance {
  param: string;
  label: string;
}

/** Humanise a provenance parameter key (snake_case → spaced words). */
export function provenanceLabel(param: string): string {
  return param.replace(/_percent\b/, ' %').replace(/_/g, ' ').trim();
}

/** Flatten a provenance map into a list of receipts (stable key order). */
export function provenanceReceipts(
  provenance: Record<string, ParamProvenance>,
): ProvenanceReceipt[] {
  return Object.entries(provenance).map(([param, p]) => ({
    ...p,
    param,
    label: provenanceLabel(param),
  }));
}

/** Format a derived value with its unit, e.g. `12 sets`, `6` (no unit). */
export function formatProvenanceValue(receipt: ParamProvenance): string {
  return receipt.unit ? `${receipt.value} ${receipt.unit}` : `${receipt.value}`;
}
