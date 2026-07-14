<script lang="ts">
  import { Chart, registerables } from 'chart.js';
  import { api } from '$lib/api';
  import { alignWeeklySeries, type OverlayRow, type VolumeWeek } from '$lib/bodycomp';
  import { chartTheme, metricColor } from '$lib/ui/chart-theme';

  Chart.register(...registerables);

  // Body composition vs training volume (plan M6): weekly counted Sets as bars,
  // body mass + lean mass trend as lines on a second axis — "is the training
  // showing up anywhere" at the whole-body level the data honestly supports
  // (no consumer device measures per-muscle growth). Weeks with no reading
  // show a gap, never an invented value.
  let canvas = $state<HTMLCanvasElement | null>(null);
  let chart: Chart | null = null;
  let rows = $state<OverlayRow[]>([]);
  let lean = $state<OverlayRow[]>([]);
  let loading = $state(true);
  let stale = $state(false);

  interface SeriesResponse {
    data?: { time: string; value: number }[];
  }

  async function load() {
    loading = true;
    try {
      const weeks = 16;
      const end = new Date();
      const start = new Date(end.getTime() - weeks * 7 * 24 * 3600 * 1000);
      const qs = `start=${start.toISOString()}&end=${end.toISOString()}&resolution=week`;
      const [volume, massRes, leanRes] = await Promise.all([
        api.get<VolumeWeek[]>(`/api/analytics/volume-series?weeks=${weeks}`),
        api
          .get<SeriesResponse>(`/api/metrics/BodyMass?${qs}`)
          .catch(() => ({ data: [] }) as SeriesResponse),
        api
          .get<SeriesResponse>(`/api/metrics/LeanBodyMass?${qs}`)
          .catch(() => ({ data: [] }) as SeriesResponse),
      ]);
      const mass = massRes.data ?? [];
      rows = alignWeeklySeries(volume, mass);
      lean = alignWeeklySeries(volume, leanRes.data ?? []);
      // Honesty flag: training weeks exist but no body reading covers them.
      stale = rows.length > 0 && rows.every((r) => r.mass === null);
      render();
    } finally {
      loading = false;
    }
  }

  function render() {
    if (!canvas || rows.length === 0) return;
    const t = chartTheme();
    chart?.destroy();
    chart = new Chart(canvas, {
      data: {
        labels: rows.map((r) => r.week_start),
        datasets: [
          {
            type: 'bar',
            label: 'Sets/week',
            data: rows.map((r) => r.sets),
            backgroundColor: `${t.accent}55`,
            borderRadius: 4,
            yAxisID: 'sets',
            order: 2,
          },
          {
            type: 'line',
            label: 'Body mass (kg)',
            data: rows.map((r) => r.mass),
            borderColor: metricColor('weight'),
            backgroundColor: metricColor('weight'),
            spanGaps: false,
            tension: 0.3,
            pointRadius: 2,
            yAxisID: 'mass',
            order: 1,
          },
          {
            type: 'line',
            label: 'Lean mass (kg)',
            data: lean.map((r) => r.mass),
            borderColor: metricColor('steps'),
            backgroundColor: metricColor('steps'),
            borderDash: [4, 3],
            spanGaps: false,
            tension: 0.3,
            pointRadius: 2,
            yAxisID: 'mass',
            order: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: t.tooltipBody, boxWidth: 10, font: { size: 10 } } },
        },
        scales: {
          x: { ticks: { color: t.tick, font: { size: 9 } }, grid: { display: false } },
          sets: {
            position: 'left',
            beginAtZero: true,
            ticks: { color: t.tick, font: { size: 9 } },
            grid: { color: t.grid },
          },
          mass: {
            position: 'right',
            ticks: { color: t.tick, font: { size: 9 } },
            grid: { display: false },
          },
        },
      },
    });
  }

  $effect(() => {
    void load();
    return () => chart?.destroy();
  });
</script>

<div class="p-4 rounded-xl bg-surface-800 border border-surface-700">
  <div class="flex items-baseline justify-between mb-2">
    <h3 class="text-sm font-semibold text-surface-100">Body comp vs training volume</h3>
    <span class="text-[10px] text-surface-500">weekly</span>
  </div>
  {#if loading}
    <div class="h-44 bg-surface-700/50 rounded-lg animate-pulse"></div>
  {:else if rows.length === 0}
    <p class="text-xs text-surface-500 py-6 text-center">
      No training weeks yet — log a few sessions and this fills in.
    </p>
  {:else}
    <div class="h-44"><canvas bind:this={canvas}></canvas></div>
    {#if stale}
      <p class="mt-2 text-[11px] text-amber-400/90">
        No recent body-mass readings — import fresh Apple Health data (or connect a
        source) to see the trend against your training.
      </p>
    {/if}
  {/if}
</div>
