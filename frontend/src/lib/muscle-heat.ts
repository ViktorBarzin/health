// Pure colour/label helpers for the muscle body-map heatmap.
//
// The visual encoding lives here as a pure module (no Svelte, no DOM) so it is
// unit-testable and shared by the BodyHeatmap component and any legend. Two
// colour scales:
//
// * **Recovery** — a red→green hue ramp: a fully-recovered (fresh) muscle is
//   green (hue 120), a fully-fatigued one is red (hue 0). This is the intuitive
//   "traffic light" every recovery-aware app uses; recovery is already a 0–100
//   score so the hue is a direct linear map.
// * **Volume** — an opacity ramp on a single accent colour, keyed to the
//   week's busiest muscle (relative intensity 0→1), matching the existing
//   HeatmapCalendar convention (untrained cells are the neutral surface colour).

/** Hue (HSL degrees) for a recovery score: 0 = red (fatigued) … 120 = green (fresh). */
export function recoveryHue(recovery: number): number {
  const clamped = Math.max(0, Math.min(100, recovery));
  return (clamped / 100) * 120;
}

/** Fill colour for a recovery score, as an `hsl()` string (red→green ramp). */
export function recoveryColor(recovery: number): string {
  // Fixed saturation/lightness so only the hue carries the signal; the lightness
  // sits a little below mid so white SVG labels stay legible on top.
  return `hsl(${recoveryHue(recovery)}, 65%, 45%)`;
}

/** Relative volume intensity in [0, 1] for a load against the window's max. */
export function volumeIntensity(load: number, maxLoad: number): number {
  if (maxLoad <= 0 || load <= 0) return 0;
  return Math.min(load / maxLoad, 1);
}

/** Neutral fill for a muscle with no volume — matches HeatmapCalendar's empty cell. */
const _NEUTRAL = '#1e293b';

/**
 * Fill colour for a volume intensity (0–1): the neutral surface at 0, else the
 * accent `color` at an alpha scaled from 0.2→1.0 (same ramp as HeatmapCalendar).
 */
export function volumeColor(intensity: number, color = '#10b981'): string {
  if (intensity <= 0) return _NEUTRAL;
  const r = parseInt(color.slice(1, 3), 16);
  const g = parseInt(color.slice(3, 5), 16);
  const b = parseInt(color.slice(5, 7), 16);
  const alpha = 0.2 + Math.min(intensity, 1) * 0.8;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** Friendly Title-Case labels for the 17 backend muscle enum values. */
export const MUSCLE_LABELS: Record<string, string> = {
  abdominals: 'Abdominals',
  abductors: 'Abductors',
  adductors: 'Adductors',
  biceps: 'Biceps',
  calves: 'Calves',
  chest: 'Chest',
  forearms: 'Forearms',
  glutes: 'Glutes',
  hamstrings: 'Hamstrings',
  lats: 'Lats',
  'lower back': 'Lower Back',
  'middle back': 'Middle Back',
  neck: 'Neck',
  quadriceps: 'Quadriceps',
  shoulders: 'Shoulders',
  traps: 'Traps',
  triceps: 'Triceps',
};

/** Human label for a muscle value, falling back to the raw value if unknown. */
export function muscleLabel(muscle: string): string {
  return MUSCLE_LABELS[muscle] ?? muscle;
}
