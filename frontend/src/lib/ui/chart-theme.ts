// Chart theming (ADR-0008): Chart.js draws to a canvas, so it can't consume the
// CSS `var(--…)` tokens directly. This resolves the live computed token values
// off <html> at chart-construction time, so charts follow the active light/dark
// theme and the metric palette lives in ONE place (the --chart-* tokens). The
// eight metric colours appear ONLY here (in data viz), never in chrome.
// SSR-safe: returns the dark-theme fallback when there's no document.

export function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined' || typeof document === 'undefined') return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/** Axis / grid / tooltip colours pulled from the semantic tokens. */
export function chartTheme() {
  return {
    tick: cssVar('--ink-3', '#71717a'),
    grid: cssVar('--edge', 'rgba(255,255,255,0.08)'),
    border: cssVar('--edge-strong', '#3a3a43'),
    tooltipBg: cssVar('--panel-2', '#1c1c21'),
    tooltipTitle: cssVar('--ink', '#f4f4f5'),
    tooltipBody: cssVar('--ink-2', '#a1a1aa'),
    accent: cssVar('--accent', '#ccff00'),
  };
}

/** The metric palette, resolved from the chart-only tokens. */
export const METRIC_COLORS: Record<string, string> = {
  heart: '#fb5d6b',
  steps: '#2fd07a',
  energy: '#f9a23b',
  sleep: '#9d7bff',
  oxygen: '#2dd4d4',
  weight: '#f472b6',
  workout: '#ff7849',
  distance: '#4d96ff',
};

export function metricColor(key: keyof typeof METRIC_COLORS): string {
  return cssVar(`--chart-${key}`, METRIC_COLORS[key]);
}
