// Tactile feedback (ADR-0008): the app responds like a precision device.
//
// One pattern per intent, fired through the Vibration API. A guarded no-op
// where unsupported (iOS Safari has no navigator.vibrate — the visual motion
// still lands). Durations are in ms; arrays are vibrate/pause/vibrate… runs.

export type HapticKind =
  | 'tick' // a value stepped / a set row touched
  | 'select' // a chip / tab chosen
  | 'success' // a set logged
  | 'pr' // a personal record — the big one
  | 'finish' // session finished
  | 'warn'; // destructive / blocked

const PATTERNS: Record<HapticKind, number | number[]> = {
  tick: 8,
  select: 12,
  success: [14, 40, 16],
  pr: [22, 45, 22, 45, 34],
  finish: [30, 55, 30],
  warn: [40, 28, 40],
};

/** The raw pattern for an intent (pure — handy for testing/inspection). */
export function patternFor(kind: HapticKind): number | number[] {
  return PATTERNS[kind];
}

/** Fire the haptic for an intent; silently does nothing where unsupported. */
export function haptic(kind: HapticKind): void {
  if (typeof navigator === 'undefined' || typeof navigator.vibrate !== 'function') return;
  try {
    navigator.vibrate(PATTERNS[kind]);
  } catch {
    /* vibration can throw if denied / detached — never break the interaction */
  }
}
