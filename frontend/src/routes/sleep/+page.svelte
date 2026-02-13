<script lang="ts">
  import { api } from '$lib/api';
  import type { MetricResponse, MetricDataPoint } from '$lib/types';
  import { dateRange } from '$lib/stores/date-range.svelte';
  import { formatNumber } from '$lib/utils/format';
  import { SLEEP_QUALITY_THRESHOLDS } from '$lib/utils/constants';
  import TimeSeriesChart from '$lib/components/charts/TimeSeriesChart.svelte';
  import BarChart from '$lib/components/charts/BarChart.svelte';

  let sleepData = $state<MetricDataPoint[]>([]);
  let stats = $state<MetricResponse['stats'] | null>(null);
  let loading = $state(true);
  let error = $state('');

  $effect(() => {
    const _s = dateRange.startISO;
    const _e = dateRange.endISO;
    const _r = dateRange.resolution;
    loadSleepData();
  });

  async function loadSleepData() {
    loading = true;
    error = '';
    try {
      const response = await api.get<MetricResponse>(
        `/api/metrics/SleepAnalysis?start=${dateRange.startISO}&end=${dateRange.endISO}&resolution=${dateRange.resolution}`
      );
      sleepData = response.data;
      stats = response.stats;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load sleep data';
      sleepData = [];
      stats = null;
    } finally {
      loading = false;
    }
  }

  let lastNightSleep = $derived.by(() => {
    if (sleepData.length === 0) return null;
    // Get the most recent data point
    const sorted = [...sleepData].sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());
    return sorted[0];
  });

  let weeklyData = $derived.by(() => {
    const now = new Date();
    const weekAgo = new Date(now);
    weekAgo.setDate(weekAgo.getDate() - 7);
    return sleepData.filter((d) => new Date(d.time) >= weekAgo);
  });

  let avgSleep = $derived(stats?.avg ?? 0);
  let minSleep = $derived(stats?.min ?? 0);
  let maxSleep = $derived(stats?.max ?? 0);

  let qualityCounts = $derived({
    excellent: sleepData.filter((d) => d.value >= SLEEP_QUALITY_THRESHOLDS.excellent).length,
    good: sleepData.filter((d) => d.value >= SLEEP_QUALITY_THRESHOLDS.good && d.value < SLEEP_QUALITY_THRESHOLDS.excellent).length,
    fair: sleepData.filter((d) => d.value >= SLEEP_QUALITY_THRESHOLDS.fair && d.value < SLEEP_QUALITY_THRESHOLDS.good).length,
    poor: sleepData.filter((d) => d.value < SLEEP_QUALITY_THRESHOLDS.fair).length,
  });

  function formatHours(hours: number): string {
    const h = Math.floor(hours);
    const m = Math.round((hours - h) * 60);
    return `${h}h ${m}m`;
  }

  function sleepQuality(hours: number): { label: string; color: string } {
    if (hours >= SLEEP_QUALITY_THRESHOLDS.excellent) return { label: 'Excellent', color: 'text-green-400' };
    if (hours >= SLEEP_QUALITY_THRESHOLDS.good) return { label: 'Good', color: 'text-primary-400' };
    if (hours >= SLEEP_QUALITY_THRESHOLDS.fair) return { label: 'Fair', color: 'text-yellow-400' };
    return { label: 'Poor', color: 'text-red-400' };
  }
</script>

<div class="space-y-6">
  {#if loading}
    <div class="space-y-6">
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-8 animate-pulse">
        <div class="flex flex-col items-center gap-3">
          <div class="w-32 h-10 bg-surface-700 rounded"></div>
          <div class="w-20 h-4 bg-surface-700 rounded"></div>
        </div>
      </div>
      <div class="grid grid-cols-3 gap-4">
        {#each Array(3) as _}
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-4 animate-pulse">
            <div class="w-16 h-3 bg-surface-700 rounded mb-2"></div>
            <div class="w-12 h-6 bg-surface-700 rounded"></div>
          </div>
        {/each}
      </div>
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 h-[300px] animate-pulse">
        <div class="w-full h-full bg-surface-700/50 rounded"></div>
      </div>
    </div>
  {:else if error}
    <div class="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400">{error}</p>
      <button
        class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm transition-colors"
        onclick={loadSleepData}
      >
        Retry
      </button>
    </div>
  {:else if sleepData.length === 0}
    <div class="p-12 text-center bg-surface-800 rounded-xl border border-surface-700">
      <svg class="w-12 h-12 text-surface-600 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
      </svg>
      <p class="text-surface-400">No sleep data available.</p>
      <p class="text-xs text-surface-500 mt-1">Import your Apple Health data to see sleep analysis.</p>
    </div>
  {:else}
    <!-- Hero: Last Night's Sleep -->
    <div class="bg-surface-800 rounded-xl border border-surface-700 p-8" data-testid="sleep-last-night">
      <div class="flex flex-col items-center">
        <p class="text-sm text-surface-500 uppercase tracking-wider mb-2">Last Night</p>
        {#if lastNightSleep}
          <p class="text-4xl font-bold text-surface-100">{formatHours(lastNightSleep.value)}</p>
          {@const quality = sleepQuality(lastNightSleep.value)}
          <p class="text-sm mt-2 {quality.color} font-medium">{quality.label}</p>
        {:else}
          <p class="text-4xl font-bold text-surface-500">--</p>
        {/if}
      </div>
    </div>

    <!-- Sleep stats -->
    <div class="grid grid-cols-3 gap-4">
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-4 text-center" data-testid="sleep-stat-avg">
        <p class="text-xs text-surface-500 uppercase tracking-wider">Average</p>
        <p class="text-lg font-semibold text-surface-100 mt-1">{formatHours(avgSleep)}</p>
      </div>
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-4 text-center" data-testid="sleep-stat-min">
        <p class="text-xs text-surface-500 uppercase tracking-wider">Shortest</p>
        <p class="text-lg font-semibold text-surface-100 mt-1">{formatHours(minSleep)}</p>
      </div>
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-4 text-center" data-testid="sleep-stat-max">
        <p class="text-xs text-surface-500 uppercase tracking-wider">Longest</p>
        <p class="text-lg font-semibold text-surface-100 mt-1">{formatHours(maxSleep)}</p>
      </div>
    </div>

    <!-- Sleep quality indicators -->
    <div class="bg-surface-800 rounded-xl border border-surface-700 p-5">
      <h3 class="text-sm font-semibold text-surface-300 mb-4">Sleep Quality Overview</h3>
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div class="flex items-center gap-3">
          <div class="w-3 h-3 rounded-full bg-green-400"></div>
          <div>
            <p class="text-sm font-medium text-surface-200">{qualityCounts.excellent}</p>
            <p class="text-xs text-surface-500">Excellent (8h+)</p>
          </div>
        </div>
        <div class="flex items-center gap-3">
          <div class="w-3 h-3 rounded-full bg-primary-400"></div>
          <div>
            <p class="text-sm font-medium text-surface-200">{qualityCounts.good}</p>
            <p class="text-xs text-surface-500">Good (7-8h)</p>
          </div>
        </div>
        <div class="flex items-center gap-3">
          <div class="w-3 h-3 rounded-full bg-yellow-400"></div>
          <div>
            <p class="text-sm font-medium text-surface-200">{qualityCounts.fair}</p>
            <p class="text-xs text-surface-500">Fair (6-7h)</p>
          </div>
        </div>
        <div class="flex items-center gap-3">
          <div class="w-3 h-3 rounded-full bg-red-400"></div>
          <div>
            <p class="text-sm font-medium text-surface-200">{qualityCounts.poor}</p>
            <p class="text-xs text-surface-500">Poor (&lt;6h)</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Weekly bar chart -->
    {#if weeklyData.length > 0}
      <div>
        <h3 class="text-sm font-semibold text-surface-300 mb-3">This Week</h3>
        <div style="height: 250px;" data-testid="sleep-weekly-chart">
          <BarChart
            data={weeklyData}
            label="Sleep (hours)"
            color="#8b5cf6"
          />
        </div>
      </div>
    {/if}

    <!-- Sleep trend over time -->
    <div>
      <h3 class="text-sm font-semibold text-surface-300 mb-3">Sleep Duration Trend</h3>
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-4" style="height: 300px;">
        <TimeSeriesChart
          data={sleepData}
          label="Sleep Duration"
          color="#8b5cf6"
          fill={true}
        />
      </div>
    </div>
  {/if}
</div>
