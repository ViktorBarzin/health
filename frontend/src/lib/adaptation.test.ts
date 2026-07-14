// Pure Block Review view-logic (ADR-0011).

import { describe, expect, it } from 'vitest';
import {
  completionTone,
  describeChange,
  isRecentRevision,
  triggerLabel,
} from './adaptation';

describe('describeChange', () => {
  it('renders volume moves with from→to', () => {
    expect(
      describeChange({ lever: 'volume', muscle: 'chest', from: 12, to: 11, reason: 'r' }),
    ).toBe('Chest: 12 → 11 sets/week');
  });
  it('renders rotations, schedule steps, succession and unknown levers', () => {
    expect(
      describeChange({ lever: 'rotation', muscle: 'lats', from: 'a', to: 'b', reason: 'r' }),
    ).toBe('Lats: movement rotated');
    expect(
      describeChange({ lever: 'days_per_week', from: 6, to: 5, reason: 'r' }),
    ).toBe('Schedule: 6 → 5 days/week');
    expect(
      describeChange({ lever: 'block_succession', from: 'x', to: 'y', reason: 'r' }),
    ).toBe('New training block generated');
    expect(describeChange({ lever: 'mystery', from: 1, to: 2, reason: 'why' })).toBe('why');
  });
});

describe('isRecentRevision', () => {
  const now = Date.parse('2026-07-14T12:00:00Z');
  it('accepts within 48h, rejects older/future/garbage', () => {
    expect(isRecentRevision('2026-07-13T13:00:00Z', now)).toBe(true);
    expect(isRecentRevision('2026-07-11T11:00:00Z', now)).toBe(false);
    expect(isRecentRevision('2026-07-15T00:00:00Z', now)).toBe(false);
    expect(isRecentRevision('not-a-date', now)).toBe(false);
  });
});

describe('labels and tones', () => {
  it('maps triggers and completion bands', () => {
    expect(triggerLabel('continuous_review')).toBe('Auto-tune');
    expect(triggerLabel('block_review')).toBe('New block');
    expect(completionTone(1.0)).toBe('good');
    expect(completionTone(0.85)).toBe('ok');
    expect(completionTone(0.5)).toBe('weak');
  });
});
