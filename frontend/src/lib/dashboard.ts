// Pure helpers for the dashboard slow-load fix (#51). No DOM, no fetch — the
// testable logic the dashboard page and chart components lean on:
//
//   - downsample / downsampleSeries: cap the number of points a chart actually
//     renders so a wide all-time window can't push thousands of points into
//     Chart.js and freeze the main thread. With day-resolution rollups a year is
//     ~365 points (a no-op), but `raw` resolution or an "All" window can be huge.
//
//   - computeDefaultWindow: choose the dashboard's INITIAL date window from the
//     per-metric `latest_time` values (GET /api/metrics/available) so it opens on
//     the user's most-recent AVAILABLE data instead of an empty trailing-30-days
//     (the user's data ends well before "today" — see ADR-0009 / the perf work).
//
// Both are unit-tested in dashboard.test.ts.

import type { MetricAvailable, MetricDataPoint } from './types';

/**
 * Default cap on the points a single chart draws. ~one-per-day for a year, which
 * comfortably covers the day/week/month rollup resolutions while still protecting
 * the renderer from a wide `raw`/all-time window. Documented, overridable per call.
 */
export const DEFAULT_MAX_POINTS = 365;

/** Default trailing window (days) the dashboard opens on, ending at the latest data. */
export const DEFAULT_WINDOW_DAYS = 90;

/** Fallback window (days) when the user has no data at all — the prior behaviour. */
export const FALLBACK_WINDOW_DAYS = 30;

/**
 * Largest-Triangle-Three-Buckets (Steinarsson 2013) downsample over an indexable
 * series, parameterised by a y-accessor so it works for both a numeric sparkline
 * and a {time, value} chart series. LTTB is the standard visual-preserving
 * downsample: it keeps the first and last points, divides the middle into
 * `threshold − 2` buckets, and from each bucket picks the point forming the
 * largest triangle with the previously-kept point and the next bucket's average —
 * so peaks and troughs survive rather than being averaged into a flat line.
 *
 * Contract:
 *   - `points.length <= threshold` → the input is returned unchanged (the SAME
 *     reference) — already small enough, nothing to do.
 *   - `threshold < 2` → at most the two endpoints (a degenerate target can't carry
 *     a "shape").
 *   - empty input → empty output.
 */
export function downsample<T>(
  points: readonly T[],
  threshold: number,
  getY: (p: T) => number,
): T[];
export function downsample(points: readonly number[], threshold: number): number[];
export function downsample<T>(
  points: readonly T[],
  threshold: number,
  getY: (p: T) => number = (p) => p as unknown as number,
): T[] {
  const n = points.length;
  if (n === 0) return [];
  if (n <= threshold) return points as T[];
  if (threshold < 2) {
    // Can't form triangles; keep the endpoints (or just the first if n===1, handled above).
    return [points[0], points[n - 1]];
  }

  const sampled: T[] = [];
  // Bucket size for the middle points (excluding the fixed first & last).
  const bucketSize = (n - 2) / (threshold - 2);

  let a = 0; // index of the previously-kept point (the triangle's left vertex)
  sampled.push(points[a]);

  for (let i = 0; i < threshold - 2; i++) {
    // The average point of the NEXT bucket (the triangle's right vertex).
    let avgX = 0;
    let avgY = 0;
    let avgRangeStart = Math.floor((i + 1) * bucketSize) + 1;
    let avgRangeEnd = Math.floor((i + 2) * bucketSize) + 1;
    avgRangeEnd = avgRangeEnd < n ? avgRangeEnd : n;
    const avgRangeLength = avgRangeEnd - avgRangeStart;
    for (; avgRangeStart < avgRangeEnd; avgRangeStart++) {
      avgX += avgRangeStart; // x is the index — uniformly spaced
      avgY += getY(points[avgRangeStart]);
    }
    avgX /= avgRangeLength;
    avgY /= avgRangeLength;

    // The current bucket we pick the representative point FROM.
    let rangeStart = Math.floor(i * bucketSize) + 1;
    const rangeEnd = Math.floor((i + 1) * bucketSize) + 1;

    const pointAX = a;
    const pointAY = getY(points[a]);

    let maxArea = -1;
    let nextA = rangeStart;
    for (; rangeStart < rangeEnd; rangeStart++) {
      // Twice the triangle area (the constant ½ is irrelevant for the argmax).
      const area = Math.abs(
        (pointAX - avgX) * (getY(points[rangeStart]) - pointAY) -
          (pointAX - rangeStart) * (avgY - pointAY),
      );
      if (area > maxArea) {
        maxArea = area;
        nextA = rangeStart;
      }
    }

    sampled.push(points[nextA]);
    a = nextA;
  }

  sampled.push(points[n - 1]);
  return sampled;
}

/**
 * Downsample a {time, value} metric series (the chart shape) to at most
 * `threshold` points via {@link downsample} keyed on `value`. Input order is
 * preserved (the endpoints and bucket picks stay in their original sequence),
 * so a chronologically-sorted series stays sorted.
 */
export function downsampleSeries(
  points: readonly MetricDataPoint[],
  threshold = DEFAULT_MAX_POINTS,
): MetricDataPoint[] {
  return downsample(points, threshold, (p) => p.value);
}

/** A resolved [start, end] window (midnight-normalised local Dates). */
export interface DefaultWindow {
  start: Date;
  end: Date;
}

/** Strip the time-of-day from a Date, returning local midnight of that day. */
function atMidnight(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/**
 * Compute the dashboard's INITIAL date window.
 *
 * The default trailing-30-days window is empty for a user whose data ended in the
 * past, so the dashboard would open blank. Instead, find the latest data instant
 * (the max `latest_time` across the available metrics) and open on the trailing
 * `windowDays` ending on that day. With no usable `latest_time` anywhere, fall
 * back to the prior last-`FALLBACK_WINDOW_DAYS`-ending-today behaviour.
 *
 * Bounds are midnight-normalised local Dates (matching the date-range store's
 * `startISO`/`endISO`, which slice the ISO day) — NOT instants, by design (a
 * non-midnight bound was a removed dead path; see the store).
 *
 * @param metrics  the GET /api/metrics/available list (each carries latest_time)
 * @param windowDays  trailing window length when data is present
 * @param now  injectable clock for the no-data fallback (defaults to new Date())
 */
export function computeDefaultWindow(
  metrics: readonly MetricAvailable[],
  windowDays = DEFAULT_WINDOW_DAYS,
  now: Date = new Date(),
): DefaultWindow {
  let latestMs = -Infinity;
  for (const m of metrics) {
    if (!m.latest_time) continue;
    const t = Date.parse(m.latest_time);
    if (!Number.isNaN(t) && t > latestMs) latestMs = t;
  }

  if (latestMs === -Infinity) {
    // No data at all → preserve the prior last-30-days-ending-today behaviour.
    const end = atMidnight(now);
    const start = new Date(end);
    start.setDate(start.getDate() - FALLBACK_WINDOW_DAYS);
    return { start, end };
  }

  const end = atMidnight(new Date(latestMs));
  const start = new Date(end);
  start.setDate(start.getDate() - windowDays);
  return { start, end };
}
