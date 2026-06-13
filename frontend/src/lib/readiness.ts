// Pure helpers for the Readiness insight UI (#14, ADR-0004).
//
// Readiness itself is computed server-side (the backend's pure core blends HRV,
// resting HR and sleep vs the user's baseline). The frontend only *renders* it.
// These small, pure transforms — the band colour, the human metric labels, the
// "X below your baseline" phrasing — are extracted here so they're unit-testable
// (vitest) rather than buried in the .svelte file, matching $lib/program.ts.

import type { ReadinessComponent } from './types';

/** A Tailwind text-colour class for a Readiness band (low/moderate/high). */
export function readinessColor(band: string | null): string {
  switch (band) {
    case 'high':
      return 'text-emerald-400';
    case 'moderate':
      return 'text-amber-400';
    case 'low':
      return 'text-red-400';
    default:
      return 'text-surface-400';
  }
}

/** A short, human label for a Readiness band. */
export function readinessBandLabel(band: string | null): string {
  switch (band) {
    case 'high':
      return 'Strong';
    case 'moderate':
      return 'Moderate';
    case 'low':
      return 'Low';
    default:
      return 'Unknown';
  }
}

/** Human label for a Readiness metric key (hrv → "HRV", etc.). */
export function metricLabel(metric: string): string {
  switch (metric) {
    case 'hrv':
      return 'HRV';
    case 'resting_hr':
      return 'Resting HR';
    case 'sleep_hours':
      return 'Sleep';
    default:
      return metric.replace(/_/g, ' ');
  }
}

/**
 * A one-line explanation of a Readiness component, e.g.
 * "HRV below your baseline" / "Sleep above your baseline". A component sitting
 * exactly at baseline reads "at your baseline".
 */
export function componentSummary(component: ReadinessComponent): string {
  const label = metricLabel(component.metric);
  if (component.direction === 'at') return `${label} at your baseline`;
  return `${label} ${component.direction} your baseline`;
}

/** The score rounded for display (null-safe → em dash). */
export function formatScore(score: number | null): string {
  return score === null ? '—' : String(Math.round(score));
}
