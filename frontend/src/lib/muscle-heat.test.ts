import { describe, expect, it } from 'vitest';
import {
  MUSCLE_LABELS,
  muscleLabel,
  recoveryColor,
  recoveryHue,
  volumeColor,
  volumeIntensity,
} from './muscle-heat';

describe('recoveryHue', () => {
  it('maps full recovery to green and zero to red', () => {
    // Hue 120 = green, 0 = red (HSL). Fresh muscle is green, fatigued is red.
    expect(recoveryHue(100)).toBeCloseTo(120, 5);
    expect(recoveryHue(0)).toBeCloseTo(0, 5);
  });

  it('is monotonic increasing in recovery (greener as you recover)', () => {
    let prev = -1;
    for (const r of [0, 25, 50, 75, 100]) {
      const hue = recoveryHue(r);
      expect(hue).toBeGreaterThan(prev);
      prev = hue;
    }
  });

  it('clamps out-of-range input into [0, 120]', () => {
    expect(recoveryHue(-50)).toBeCloseTo(0, 5);
    expect(recoveryHue(150)).toBeCloseTo(120, 5);
  });
});

describe('recoveryColor', () => {
  it('returns an hsl() string', () => {
    expect(recoveryColor(100)).toMatch(/^hsl\(/);
  });

  it('a fresher muscle and a more-fatigued muscle render different colors', () => {
    expect(recoveryColor(100)).not.toBe(recoveryColor(20));
  });
});

describe('volumeIntensity', () => {
  it('is 0 when there is no volume', () => {
    expect(volumeIntensity(0, 1000)).toBe(0);
  });

  it('is 1 at the max load and proportional below it', () => {
    expect(volumeIntensity(1000, 1000)).toBe(1);
    expect(volumeIntensity(500, 1000)).toBeCloseTo(0.5, 5);
  });

  it('is 0 (not NaN) when the max is 0 — empty week', () => {
    expect(volumeIntensity(0, 0)).toBe(0);
  });

  it('never exceeds 1 even if a value is above the supplied max', () => {
    expect(volumeIntensity(2000, 1000)).toBe(1);
  });
});

describe('volumeColor', () => {
  it('renders untrained (intensity 0) as the neutral surface color', () => {
    // Matches HeatmapCalendar's empty-cell convention.
    expect(volumeColor(0)).toBe('#1e293b');
  });

  it('renders a higher intensity as a more opaque accent than a lower one', () => {
    const low = volumeColor(0.2);
    const high = volumeColor(0.9);
    expect(low).not.toBe(high);
    expect(high).toMatch(/^rgba\(/);
  });
});

describe('MUSCLE_LABELS / muscleLabel', () => {
  it('covers every muscle enum value the backend can emit', () => {
    const expected = [
      'abdominals', 'abductors', 'adductors', 'biceps', 'calves', 'chest',
      'forearms', 'glutes', 'hamstrings', 'lats', 'lower back', 'middle back',
      'neck', 'quadriceps', 'shoulders', 'traps', 'triceps',
    ];
    for (const m of expected) {
      expect(MUSCLE_LABELS[m]).toBeTruthy();
    }
  });

  it('falls back to the raw value for an unknown muscle', () => {
    expect(muscleLabel('unknownium')).toBe('unknownium');
  });

  it('returns the friendly label for a known muscle', () => {
    expect(muscleLabel('lower back')).toBe('Lower Back');
  });
});
