// Pure body-comp vs training-volume alignment (plan M6) — no IO (vitest).
//
// The overlay chart plots weekly counted Sets (bars) against the body-mass /
// lean-mass trend (line). Health readings are irregular; each training week
// takes the LATEST reading at or before that week's end — never interpolated,
// null when no reading exists yet (the chart shows the gap honestly).

export interface VolumeWeek {
  week_start: string; // ISO date (Monday)
  sets: number;
}

export interface MetricPoint {
  time: string; // ISO datetime
  value: number;
}

export interface OverlayRow {
  week_start: string;
  sets: number;
  mass: number | null;
}

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;

export function alignWeeklySeries(
  volume: VolumeWeek[],
  mass: MetricPoint[],
): OverlayRow[] {
  const readings = mass
    .map((p) => ({ t: Date.parse(p.time), v: p.value }))
    .filter((p) => !Number.isNaN(p.t))
    .sort((a, b) => a.t - b.t);
  return volume.map((w) => {
    const weekEnd = Date.parse(`${w.week_start}T00:00:00Z`) + WEEK_MS;
    let latest: number | null = null;
    for (const r of readings) {
      if (r.t < weekEnd) latest = r.v;
      else break;
    }
    return { week_start: w.week_start, sets: w.sets, mass: latest };
  });
}
