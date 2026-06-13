import { describe, expect, it } from 'vitest';
import type { ReadinessComponent } from './types';
import {
  componentSummary,
  formatScore,
  metricLabel,
  readinessBandLabel,
  readinessColor,
} from './readiness';

function component(
  metric: string,
  direction: 'above' | 'below' | 'at',
): ReadinessComponent {
  return { metric, recent: 1, baseline: 1, score: 50, weight: 0.5, direction };
}

describe('readinessColor', () => {
  it('maps each band to a distinct colour', () => {
    expect(readinessColor('high')).toContain('emerald');
    expect(readinessColor('moderate')).toContain('amber');
    expect(readinessColor('low')).toContain('red');
  });

  it('falls back for an unknown / null band', () => {
    expect(readinessColor(null)).toContain('surface');
  });
});

describe('readinessBandLabel', () => {
  it('labels the bands', () => {
    expect(readinessBandLabel('high')).toBe('Strong');
    expect(readinessBandLabel('moderate')).toBe('Moderate');
    expect(readinessBandLabel('low')).toBe('Low');
    expect(readinessBandLabel(null)).toBe('Unknown');
  });
});

describe('metricLabel', () => {
  it('renders friendly metric names', () => {
    expect(metricLabel('hrv')).toBe('HRV');
    expect(metricLabel('resting_hr')).toBe('Resting HR');
    expect(metricLabel('sleep_hours')).toBe('Sleep');
  });
});

describe('componentSummary', () => {
  it('phrases the deviation against the baseline', () => {
    expect(componentSummary(component('hrv', 'below'))).toBe('HRV below your baseline');
    expect(componentSummary(component('sleep_hours', 'above'))).toBe('Sleep above your baseline');
    expect(componentSummary(component('resting_hr', 'at'))).toBe('Resting HR at your baseline');
  });
});

describe('formatScore', () => {
  it('rounds a numeric score', () => {
    expect(formatScore(48.6)).toBe('49');
  });

  it('renders an em dash for null', () => {
    expect(formatScore(null)).toBe('—');
  });
});
