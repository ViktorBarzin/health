import type { MetricAvailable } from '$lib/types';
import { computeDefaultWindow, DEFAULT_WINDOW_DAYS } from '$lib/dashboard';

export type Resolution = 'raw' | 'day' | 'week' | 'month';
export type Preset = '7d' | '30d' | '90d' | '1y' | 'all';

function createDateRangeStore() {
  const now = new Date();
  const thirtyDaysAgo = new Date(now);
  thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

  let start = $state<Date>(thirtyDaysAgo);
  let end = $state<Date>(now);
  let resolution = $state<Resolution>('day');
  let activePreset = $state<Preset | null>('30d');
  // Whether the data-driven initial window (computeDefaultWindow) has been
  // applied yet. Guards single-application: re-mounting the dashboard, or any
  // manual preset/range change, must NOT later get clobbered by a default.
  let defaultApplied = $state(false);

  function setRange(newStart: Date, newEnd: Date) {
    start = newStart;
    end = newEnd;
    activePreset = null;
    // A manual choice counts as "the default no longer applies".
    defaultApplied = true;
  }

  function setResolution(res: Resolution) {
    resolution = res;
  }

  function setPreset(preset: Preset) {
    const today = new Date();
    let newStart: Date;

    switch (preset) {
      case '7d':
        newStart = new Date(today);
        newStart.setDate(today.getDate() - 7);
        break;
      case '30d':
        newStart = new Date(today);
        newStart.setDate(today.getDate() - 30);
        break;
      case '90d':
        newStart = new Date(today);
        newStart.setDate(today.getDate() - 90);
        break;
      case '1y':
        newStart = new Date(today);
        newStart.setFullYear(today.getFullYear() - 1);
        break;
      case 'all':
        newStart = new Date(2015, 0, 1);
        break;
    }

    start = newStart;
    end = today;
    activePreset = preset;
    defaultApplied = true;
  }

  /**
   * Apply the data-driven INITIAL window once: clamp the range to end at the
   * user's most-recent available data (the trailing DEFAULT_WINDOW_DAYS), so the
   * dashboard opens on real data rather than an empty last-30-days. No-op if the
   * user has already chosen a preset/range this session, or if it has already
   * run. With no data, computeDefaultWindow returns the last-30-days fallback so
   * the behaviour is unchanged. Returns true iff it applied.
   */
  function applyDefaultWindow(metrics: readonly MetricAvailable[]): boolean {
    if (defaultApplied) return false;
    const win = computeDefaultWindow(metrics, DEFAULT_WINDOW_DAYS);
    start = win.start;
    end = win.end;
    activePreset = null;
    defaultApplied = true;
    return true;
  }

  return {
    get start() { return start; },
    get end() { return end; },
    get resolution() { return resolution; },
    get activePreset() { return activePreset; },
    get defaultApplied() { return defaultApplied; },
    get startISO() { return start.toISOString().slice(0, 10); },
    get endISO() { return end.toISOString().slice(0, 10); },
    setRange,
    setResolution,
    setPreset,
    applyDefaultWindow,
  };
}

export const dateRange = createDateRangeStore();
