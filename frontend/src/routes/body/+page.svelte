<script lang="ts">
  import { api } from '$lib/api';
  import type { MetricResponse, MetricDataPoint } from '$lib/types';
  import { dateRange } from '$lib/stores/date-range.svelte';
  import { formatNumber, formatMetricValue } from '$lib/utils/format';
  import { BMI_CATEGORIES } from '$lib/utils/constants';
  import TimeSeriesChart from '$lib/components/charts/TimeSeriesChart.svelte';

  let weightData = $state<MetricDataPoint[]>([]);
  let weightStats = $state<MetricResponse['stats'] | null>(null);
  let bodyFatData = $state<MetricDataPoint[]>([]);
  let bodyFatStats = $state<MetricResponse['stats'] | null>(null);
  let bmiData = $state<MetricDataPoint[]>([]);
  let bmiStats = $state<MetricResponse['stats'] | null>(null);
  let loading = $state(true);
  let error = $state('');

  $effect(() => {
    const _s = dateRange.startISO;
    const _e = dateRange.endISO;
    const _r = dateRange.resolution;
    loadData();
  });

  async function loadData() {
    loading = true;
    error = '';

    const params = `?start=${dateRange.startISO}&end=${dateRange.endISO}&resolution=${dateRange.resolution}`;

    try {
      const results = await Promise.allSettled([
        api.get<MetricResponse>(`/api/metrics/BodyMass${params}`),
        api.get<MetricResponse>(`/api/metrics/BodyFatPercentage${params}`),
        api.get<MetricResponse>(`/api/metrics/BodyMassIndex${params}`),
      ]);

      if (results[0].status === 'fulfilled') {
        weightData = results[0].value.data;
        weightStats = results[0].value.stats;
      }
      if (results[1].status === 'fulfilled') {
        bodyFatData = results[1].value.data;
        bodyFatStats = results[1].value.stats;
      }
      if (results[2].status === 'fulfilled') {
        bmiData = results[2].value.data;
        bmiStats = results[2].value.stats;
      }

      // If all failed, show an error
      if (results.every((r) => r.status === 'rejected')) {
        error = 'Failed to load body composition data';
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load data';
    } finally {
      loading = false;
    }
  }

  let currentWeight = $derived.by(() => {
    if (weightData.length === 0) return null;
    const sorted = [...weightData].sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());
    return sorted[0];
  });

  let currentBodyFat = $derived.by(() => {
    if (bodyFatData.length === 0) return null;
    const sorted = [...bodyFatData].sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());
    return sorted[0];
  });

  let currentBmi = $derived.by(() => {
    if (bmiData.length === 0) return null;
    const sorted = [...bmiData].sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime());
    return sorted[0];
  });

  // Compute 7-day moving average for weight
  let weightWithMA = $derived.by(() => {
    if (weightData.length < 2) return weightData;
    const sorted = [...weightData].sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime());
    const ma: MetricDataPoint[] = [];
    for (let i = 0; i < sorted.length; i++) {
      const windowStart = Math.max(0, i - 6);
      const window = sorted.slice(windowStart, i + 1);
      const avg = window.reduce((sum, d) => sum + d.value, 0) / window.length;
      ma.push({ time: sorted[i].time, value: Math.round(avg * 10) / 10 });
    }
    return ma;
  });

  function bmiCategory(bmi: number): { label: string; color: string } {
    const cat = BMI_CATEGORIES.find((c) => bmi < c.max);
    return cat ? { label: cat.label, color: cat.color } : { label: 'Obese', color: 'text-red-400' };
  }
</script>

<div class="space-y-6">
  {#if loading}
    <div class="space-y-6">
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {#each Array(3) as _}
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 animate-pulse">
            <div class="flex flex-col items-center gap-3">
              <div class="w-20 h-4 bg-surface-700 rounded"></div>
              <div class="w-24 h-8 bg-surface-700 rounded"></div>
            </div>
          </div>
        {/each}
      </div>
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 h-[350px] animate-pulse">
        <div class="w-full h-full bg-surface-700/50 rounded"></div>
      </div>
    </div>
  {:else if error && weightData.length === 0 && bodyFatData.length === 0 && bmiData.length === 0}
    <div class="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400">{error}</p>
      <button
        class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm transition-colors"
        onclick={loadData}
      >
        Retry
      </button>
    </div>
  {:else}
    <!-- Hero metrics -->
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
      <!-- Weight -->
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 text-center" data-testid="body-current-weight">
        <p class="text-xs text-surface-500 uppercase tracking-wider mb-2">Current Weight</p>
        {#if currentWeight}
          <p class="text-3xl font-bold text-surface-100">
            {currentWeight.value.toFixed(1)}
            <span class="text-lg text-surface-400 font-normal">kg</span>
          </p>
          {#if weightStats?.trend_pct !== undefined && weightStats.trend_pct !== null}
            <p class="text-sm mt-1 {weightStats.trend_pct > 0 ? 'text-red-400' : weightStats.trend_pct < 0 ? 'text-green-400' : 'text-surface-400'}">
              {weightStats.trend_pct > 0 ? '+' : ''}{weightStats.trend_pct.toFixed(1)}%
            </p>
          {/if}
        {:else}
          <p class="text-3xl font-bold text-surface-500">--</p>
        {/if}
      </div>

      <!-- Body Fat -->
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 text-center">
        <p class="text-xs text-surface-500 uppercase tracking-wider mb-2">Body Fat</p>
        {#if currentBodyFat}
          <p class="text-3xl font-bold text-surface-100">
            {currentBodyFat.value.toFixed(1)}
            <span class="text-lg text-surface-400 font-normal">%</span>
          </p>
          {#if bodyFatStats?.trend_pct !== undefined && bodyFatStats.trend_pct !== null}
            <p class="text-sm mt-1 {bodyFatStats.trend_pct > 0 ? 'text-red-400' : bodyFatStats.trend_pct < 0 ? 'text-green-400' : 'text-surface-400'}">
              {bodyFatStats.trend_pct > 0 ? '+' : ''}{bodyFatStats.trend_pct.toFixed(1)}%
            </p>
          {/if}
        {:else}
          <p class="text-3xl font-bold text-surface-500">--</p>
          <p class="text-xs text-surface-600 mt-1">No data available</p>
        {/if}
      </div>

      <!-- BMI -->
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 text-center" data-testid="body-current-bmi">
        <p class="text-xs text-surface-500 uppercase tracking-wider mb-2">BMI</p>
        {#if currentBmi}
          <p class="text-3xl font-bold text-surface-100">
            {currentBmi.value.toFixed(1)}
          </p>
          {@const cat = bmiCategory(currentBmi.value)}
          <p class="text-sm mt-1 {cat.color} font-medium">{cat.label}</p>
        {:else}
          <p class="text-3xl font-bold text-surface-500">--</p>
          <p class="text-xs text-surface-600 mt-1">No data available</p>
        {/if}
      </div>
    </div>

    <!-- Weight trend with moving average -->
    {#if weightData.length > 0}
      <div>
        <h3 class="text-sm font-semibold text-surface-300 mb-3">Weight Trend</h3>
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-4" style="height: 350px;" data-testid="body-weight-chart">
          <TimeSeriesChart
            data={weightData}
            label="Weight"
            color="#ec4899"
            fill={false}
          />
        </div>
      </div>

      <!-- Weight stats -->
      {#if weightStats}
        <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
            <p class="text-xs text-surface-500 uppercase tracking-wider">Average</p>
            <p class="text-lg font-semibold text-surface-100 mt-1">{weightStats.avg.toFixed(1)} kg</p>
          </div>
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
            <p class="text-xs text-surface-500 uppercase tracking-wider">Min</p>
            <p class="text-lg font-semibold text-surface-100 mt-1">{weightStats.min.toFixed(1)} kg</p>
          </div>
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
            <p class="text-xs text-surface-500 uppercase tracking-wider">Max</p>
            <p class="text-lg font-semibold text-surface-100 mt-1">{weightStats.max.toFixed(1)} kg</p>
          </div>
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
            <p class="text-xs text-surface-500 uppercase tracking-wider">Measurements</p>
            <p class="text-lg font-semibold text-surface-100 mt-1">{formatNumber(weightStats.count)}</p>
          </div>
        </div>
      {/if}
    {/if}

    <!-- Body fat trend -->
    {#if bodyFatData.length > 0}
      <div>
        <h3 class="text-sm font-semibold text-surface-300 mb-3">Body Fat Trend</h3>
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-4" style="height: 300px;">
          <TimeSeriesChart
            data={bodyFatData}
            label="Body Fat %"
            color="#a78bfa"
            fill={true}
          />
        </div>
      </div>
    {/if}

    <!-- BMI trend -->
    {#if bmiData.length > 0}
      <div>
        <h3 class="text-sm font-semibold text-surface-300 mb-3">BMI Trend</h3>
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-4" style="height: 300px;">
          <TimeSeriesChart
            data={bmiData}
            label="BMI"
            color="#f472b6"
            fill={true}
          />
        </div>
      </div>
    {/if}

    {#if weightData.length === 0 && bodyFatData.length === 0 && bmiData.length === 0}
      <div class="p-12 text-center bg-surface-800 rounded-xl border border-surface-700">
        <svg class="w-12 h-12 text-surface-600 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
        </svg>
        <p class="text-surface-400">No body composition data available.</p>
        <p class="text-xs text-surface-500 mt-1">Import your Apple Health data to see body metrics.</p>
      </div>
    {/if}
  {/if}
</div>
