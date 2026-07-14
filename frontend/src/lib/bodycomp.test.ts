// Pure body-comp overlay alignment (plan M6).

import { describe, expect, it } from 'vitest';
import { alignWeeklySeries } from './bodycomp';

const vol = [
  { week_start: '2026-06-01', sets: 10 },
  { week_start: '2026-06-08', sets: 12 },
  { week_start: '2026-06-15', sets: 8 },
];

describe('alignWeeklySeries', () => {
  it('takes the latest reading at or before each week end, never interpolates', () => {
    const mass = [
      { time: '2026-06-03T08:00:00Z', value: 80.0 },
      { time: '2026-06-10T08:00:00Z', value: 79.5 },
    ];
    expect(alignWeeklySeries(vol, mass)).toEqual([
      { week_start: '2026-06-01', sets: 10, mass: 80.0 },
      { week_start: '2026-06-08', sets: 12, mass: 79.5 },
      { week_start: '2026-06-15', sets: 8, mass: 79.5 }, // carried, not invented
    ]);
  });

  it('yields null before the first reading and handles unsorted/garbage input', () => {
    const mass = [
      { time: '2026-06-12T08:00:00Z', value: 79.0 },
      { time: 'not-a-date', value: 1 },
      { time: '2026-06-09T08:00:00Z', value: 79.8 },
    ];
    const rows = alignWeeklySeries(vol, mass);
    expect(rows[0].mass).toBeNull(); // week ends before any reading
    expect(rows[1].mass).toBe(79.0); // latest ≤ week end wins after sorting
  });

  it('empty inputs stay empty/null', () => {
    expect(alignWeeklySeries([], [])).toEqual([]);
    expect(alignWeeklySeries(vol, []).every((r) => r.mass === null)).toBe(true);
  });
});
