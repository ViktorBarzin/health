import { describe, expect, it } from 'vitest';
import {
  DEFAULT_MAX_POINTS,
  computeDefaultWindow,
  downsample,
  downsampleSeries,
} from './dashboard';
import type { MetricAvailable, MetricDataPoint } from './types';

// Pure helpers for the dashboard perf fix (#51):
//   - downsample: cap the points a chart actually draws (≤ N) so a wide
//     all-time window can't flood the renderer and freeze the main thread.
//     Largest-Triangle-Three-Buckets — preserves the first/last point and the
//     visual shape (peaks/troughs), passes input through unchanged when already
//     ≤ N, and handles the empty case.
//   - computeDefaultWindow: given the per-metric latest_time values from
//     GET /api/metrics/available, pick the INITIAL [start, end] so the dashboard
//     opens on the user's most-recent AVAILABLE data (the trailing window ending
//     at the latest instant) instead of an empty last-30-days. No data → the
//     last-30-days fallback.

// --- downsample ---------------------------------------------------------------

describe('downsample (numbers)', () => {
  it('returns the input unchanged when already at or below the threshold', () => {
    const input = [1, 2, 3, 4, 5];
    expect(downsample(input, 10)).toEqual(input);
    expect(downsample(input, 5)).toEqual(input);
  });

  it('returns an empty array unchanged', () => {
    expect(downsample([], 100)).toEqual([]);
  });

  it('caps the output at the threshold for a large series', () => {
    const input = Array.from({ length: 5000 }, (_, i) => i);
    const out = downsample(input, 365);
    expect(out.length).toBeLessThanOrEqual(365);
    expect(out.length).toBeGreaterThan(0);
  });

  it('preserves the first and last data point exactly', () => {
    const input = Array.from({ length: 1000 }, (_, i) => Math.sin(i / 20) * 100);
    const out = downsample(input, 50);
    expect(out[0]).toBe(input[0]);
    expect(out[out.length - 1]).toBe(input[input.length - 1]);
  });

  it('preserves a prominent spike (shape) rather than averaging it away', () => {
    // A flat line with one tall spike in the middle.
    const input = Array.from({ length: 1000 }, (_, i) => (i === 500 ? 1000 : 1));
    const out = downsample(input, 20);
    expect(Math.max(...out)).toBe(1000);
  });

  it('handles a threshold below 2 by clamping to the endpoints', () => {
    const input = [5, 6, 7, 8, 9];
    const out = downsample(input, 1);
    // Degenerate target: never returns more than 2 (the two anchors).
    expect(out.length).toBeLessThanOrEqual(2);
    expect(out[0]).toBe(5);
    expect(out[out.length - 1]).toBe(9);
  });
});

describe('downsampleSeries ({time,value}[])', () => {
  const makePoints = (n: number): MetricDataPoint[] =>
    Array.from({ length: n }, (_, i) => ({
      time: new Date(2026, 0, 1 + i).toISOString(),
      value: Math.cos(i / 15) * 50 + 50,
    }));

  it('passes a short series through unchanged', () => {
    const pts = makePoints(10);
    expect(downsampleSeries(pts, 365)).toEqual(pts);
  });

  it('caps a long series and keeps the endpoints', () => {
    const pts = makePoints(4000);
    const out = downsampleSeries(pts, 365);
    expect(out.length).toBeLessThanOrEqual(365);
    expect(out[0]).toEqual(pts[0]);
    expect(out[out.length - 1]).toEqual(pts[pts.length - 1]);
  });

  it('returns datapoints in chronological order', () => {
    const pts = makePoints(2000);
    const out = downsampleSeries(pts, 200);
    for (let i = 1; i < out.length; i++) {
      expect(out[i].time >= out[i - 1].time).toBe(true);
    }
  });

  it('returns [] for empty input', () => {
    expect(downsampleSeries([], 365)).toEqual([]);
  });
});

// --- computeDefaultWindow -----------------------------------------------------

function metric(latest: string | null): MetricAvailable {
  return {
    metric_type: 'StepCount',
    unit: 'count',
    count: 1,
    latest_time: latest as string,
  };
}

describe('computeDefaultWindow', () => {
  it('ends the window at the max latest_time across metrics', () => {
    const metrics = [
      metric('2026-01-10T08:00:00Z'),
      metric('2026-02-12T23:30:00Z'), // the latest instant
      metric('2025-12-01T00:00:00Z'),
    ];
    const { start, end } = computeDefaultWindow(metrics, 90);
    // end is the calendar day of the latest data (midnight bounds, per the store).
    expect(end.toISOString().slice(0, 10)).toBe('2026-02-12');
  });

  it('starts the window `windowDays` before the end', () => {
    const metrics = [metric('2026-02-12T12:00:00Z')];
    const { start, end } = computeDefaultWindow(metrics, 90);
    const diffDays = Math.round(
      (end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24),
    );
    expect(diffDays).toBe(90);
  });

  it('uses normalised (midnight) bounds — no time-of-day component', () => {
    const metrics = [metric('2026-02-12T17:45:13Z')];
    const { start, end } = computeDefaultWindow(metrics, 90);
    expect(end.getHours()).toBe(0);
    expect(end.getMinutes()).toBe(0);
    expect(end.getSeconds()).toBe(0);
    expect(start.getHours()).toBe(0);
  });

  it('falls back to the last 30 days ending today when there is no data', () => {
    const now = new Date(2026, 5, 14, 9, 30); // 2026-06-14
    const { start, end } = computeDefaultWindow([], 90, now);
    expect(end.toISOString().slice(0, 10)).toBe('2026-06-14');
    const diffDays = Math.round(
      (end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24),
    );
    expect(diffDays).toBe(30);
  });

  it('falls back when every metric has a null/empty latest_time', () => {
    const now = new Date(2026, 5, 14, 9, 30);
    const metrics = [metric(null), metric('')];
    const { start, end } = computeDefaultWindow(metrics, 90, now);
    expect(end.toISOString().slice(0, 10)).toBe('2026-06-14');
    const diffDays = Math.round(
      (end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24),
    );
    expect(diffDays).toBe(30);
  });

  it('ignores unparseable latest_time values and uses the valid max', () => {
    const metrics = [
      metric('not-a-date'),
      metric('2026-01-05T00:00:00Z'),
    ];
    const { end } = computeDefaultWindow(metrics, 90);
    expect(end.toISOString().slice(0, 10)).toBe('2026-01-05');
  });

  it('exposes a sensible default max-points constant', () => {
    expect(DEFAULT_MAX_POINTS).toBeGreaterThanOrEqual(180);
    expect(DEFAULT_MAX_POINTS).toBeLessThanOrEqual(1000);
  });
});
