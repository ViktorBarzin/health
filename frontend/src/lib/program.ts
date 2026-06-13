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

/** Format a provenance range, e.g. `10–20 sets`, `≥2 sessions`, `value` only. */
export function formatProvenanceRange(receipt: ParamProvenance): string {
  const unit = receipt.unit ? ` ${receipt.unit}` : '';
  if (receipt.min !== null && receipt.max !== null) {
    return `${receipt.min}–${receipt.max}${unit}`;
  }
  if (receipt.min !== null) return `≥${receipt.min}${unit}`;
  if (receipt.max !== null) return `≤${receipt.max}${unit}`;
  return `${receipt.value}${unit}`;
}

/** The distinct Principle keys a Program was built from (stable order). */
export function provenancePrincipleKeys(
  provenance: Record<string, ParamProvenance>,
): string[] {
  const seen: string[] = [];
  for (const p of Object.values(provenance)) {
    if (!seen.includes(p.principle_key)) seen.push(p.principle_key);
  }
  return seen;
}

/** Human label + Tailwind colour for an evidence grade (A/B/C). */
export function evidenceGradeLabel(grade: string): string {
  switch (grade) {
    case 'A':
      return 'Strong evidence';
    case 'B':
      return 'Moderate evidence';
    case 'C':
      return 'Limited evidence';
    default:
      return grade;
  }
}

export function evidenceGradeColor(grade: string): string {
  switch (grade) {
    case 'A':
      return 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10';
    case 'B':
      return 'text-amber-400 border-amber-500/40 bg-amber-500/10';
    case 'C':
      return 'text-orange-400 border-orange-500/40 bg-orange-500/10';
    default:
      return 'text-surface-400 border-surface-600 bg-surface-800';
  }
}
