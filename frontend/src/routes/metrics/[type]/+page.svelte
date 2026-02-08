<script lang="ts">
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import type { MetricResponse, MetricDataPoint } from '$lib/types';
  import { dateRange, type Resolution } from '$lib/stores/date-range.svelte';
  import { METRIC_LABELS, METRIC_COLORS, METRIC_UNITS } from '$lib/utils/constants';
  import { formatNumber, formatMetricValue } from '$lib/utils/format';
  import TimeSeriesChart from '$lib/components/charts/TimeSeriesChart.svelte';
  import HeatmapCalendar from '$lib/components/charts/HeatmapCalendar.svelte';
  import Histogram from '$lib/components/charts/Histogram.svelte';

  let metricType = $derived($page.params.type);
  let metricLabel = $derived(METRIC_LABELS[metricType] ?? metricType.replace(/([A-Z])/g, ' $1').trim());
  let metricColor = $derived(METRIC_COLORS[metricType] ?? '#10b981');
  let metricUnit = $derived(METRIC_UNITS[metricType] ?? '');

  let data = $state<MetricDataPoint[]>([]);
  let stats = $state<MetricResponse['stats'] | null>(null);
  let loading = $state(true);
  let error = $state('');

  const resolutions: { value: Resolution; label: string }[] = [
    { value: 'raw', label: 'Raw' },
    { value: 'day', label: 'Day' },
    { value: 'week', label: 'Week' },
    { value: 'month', label: 'Month' },
  ];

  $effect(() => {
    // Track reactive dependencies to trigger refetch
    const _type = metricType;
    const _start = dateRange.startISO;
    const _end = dateRange.endISO;
    const _res = dateRange.resolution;
    loadData();
  });

  async function loadData() {
    loading = true;
    error = '';
    try {
      const response = await api.get<MetricResponse>(
        `/api/metrics/${metricType}?start=${dateRange.startISO}&end=${dateRange.endISO}&resolution=${dateRange.resolution}`
      );
      data = response.data;
      stats = response.stats;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load metric data';
      data = [];
      stats = null;
    } finally {
      loading = false;
    }
  }

  let heatmapData = $derived.by(() => {
    const map = new Map<string, number>();
    for (const d of data) {
      const day = d.time.slice(0, 10);
      map.set(day, (map.get(day) ?? 0) + d.value);
    }
    return map;
  });

  let histogramValues = $derived(data.map((d) => d.value));

  let trendDirection = $derived.by(() => {
    if (!stats?.trend_pct) return 'neutral';
    return stats.trend_pct > 0 ? 'up' : 'down';
  });
</script>

<div class="space-y-6">
  <!-- Header -->
  <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
    <div class="flex items-center gap-3">
      <a
        href="/metrics"
        class="p-1.5 rounded-lg text-surface-400 hover:text-surface-200 hover:bg-surface-800 transition-colors"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
        </svg>
      </a>
      <div>
        <h1 class="text-xl font-bold text-surface-100">{metricLabel}</h1>
        <p class="text-sm text-surface-500">
          {metricUnit ? metricUnit : 'value'}
          {#if stats}
            &middot; {formatNumber(stats.count)} data points
          {/if}
        </p>
      </div>
    </div>

    <!-- Resolution toggle -->
    <div class="flex items-center rounded-lg bg-surface-800 p-0.5">
      {#each resolutions as res}
        <button
          class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors
                 {dateRange.resolution === res.value
                   ? 'bg-accent-600 text-white'
                   : 'text-surface-400 hover:text-surface-200'}"
          onclick={() => dateRange.setResolution(res.value)}
        >
          {res.label}
        </button>
      {/each}
    </div>
  </div>

  {#if loading}
    <div class="space-y-6">
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 h-[350px] animate-pulse">
        <div class="w-full h-full bg-surface-700/50 rounded-lg"></div>
      </div>
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {#each Array(4) as _}
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-4 animate-pulse">
            <div class="w-12 h-3 bg-surface-700 rounded mb-2"></div>
            <div class="w-16 h-6 bg-surface-700 rounded"></div>
          </div>
        {/each}
      </div>
    </div>
  {:else if error}
    <div class="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400">{error}</p>
      <button
        class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm transition-colors"
        onclick={loadData}
      >
        Retry
      </button>
    </div>
  {:else if data.length === 0}
    <div class="p-12 text-center bg-surface-800 rounded-xl border border-surface-700">
      <svg class="w-12 h-12 text-surface-600 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
      </svg>
      <p class="text-surface-400">No data available for this time range.</p>
      <p class="text-xs text-surface-500 mt-1">Try expanding the date range.</p>
    </div>
  {:else}
    <!-- Time series chart -->
    <div class="bg-surface-800 rounded-xl border border-surface-700 p-4" style="height: 350px;">
      <TimeSeriesChart
        {data}
        label={metricLabel}
        color={metricColor}
        fill={true}
      />
    </div>

    <!-- Stats panel -->
    {#if stats}
      <div class="grid grid-cols-2 sm:grid-cols-5 gap-4">
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
          <p class="text-xs text-surface-500 uppercase tracking-wider">Average</p>
          <p class="text-lg font-semibold text-surface-100 mt-1">
            {formatMetricValue(stats.avg, metricUnit)}
          </p>
        </div>
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
          <p class="text-xs text-surface-500 uppercase tracking-wider">Min</p>
          <p class="text-lg font-semibold text-surface-100 mt-1">
            {formatMetricValue(stats.min, metricUnit)}
          </p>
        </div>
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
          <p class="text-xs text-surface-500 uppercase tracking-wider">Max</p>
          <p class="text-lg font-semibold text-surface-100 mt-1">
            {formatMetricValue(stats.max, metricUnit)}
          </p>
        </div>
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
          <p class="text-xs text-surface-500 uppercase tracking-wider">Count</p>
          <p class="text-lg font-semibold text-surface-100 mt-1">
            {formatNumber(stats.count)}
          </p>
        </div>
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
          <p class="text-xs text-surface-500 uppercase tracking-wider">Trend</p>
          <div class="flex items-center gap-1 mt-1">
            {#if stats.trend_pct !== undefined && stats.trend_pct !== null}
              <svg
                class="w-4 h-4 {trendDirection === 'up' ? 'text-green-400' : trendDirection === 'down' ? 'text-red-400' : 'text-surface-400'}"
                fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"
              >
                {#if trendDirection === 'up'}
                  <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 19.5l15-15m0 0H8.25m11.25 0v11.25" />
                {:else if trendDirection === 'down'}
                  <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 4.5l15 15m0 0V8.25m0 11.25H8.25" />
                {:else}
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 12h-15" />
                {/if}
              </svg>
              <span class="text-lg font-semibold {trendDirection === 'up' ? 'text-green-400' : trendDirection === 'down' ? 'text-red-400' : 'text-surface-400'}">
                {Math.abs(stats.trend_pct).toFixed(1)}%
              </span>
            {:else}
              <span class="text-lg font-semibold text-surface-500">--</span>
            {/if}
          </div>
        </div>
      </div>
    {/if}

    <!-- Heatmap calendar -->
    <div>
      <h3 class="text-sm font-semibold text-surface-300 mb-3">Daily Heatmap</h3>
      <HeatmapCalendar data={heatmapData} color={metricColor} />
    </div>

    <!-- Histogram -->
    {#if histogramValues.length > 1}
      <div>
        <h3 class="text-sm font-semibold text-surface-300 mb-3">Value Distribution</h3>
        <div style="height: 250px;">
          <Histogram
            values={histogramValues}
            label={metricLabel}
            color={metricColor}
            unit={metricUnit}
          />
        </div>
      </div>
    {/if}
  {/if}
</div>
