<script lang="ts">
  import { api } from '$lib/api';
  import type { MetricAvailable, MetricResponse, MetricDataPoint } from '$lib/types';
  import { dateRange } from '$lib/stores/date-range.svelte';
  import { METRIC_LABELS, METRIC_COLORS, METRIC_UNITS } from '$lib/utils/constants';
  import { formatMetricValue, formatNumber } from '$lib/utils/format';
  import TimeSeriesChart from '$lib/components/charts/TimeSeriesChart.svelte';
  import ScatterPlot from '$lib/components/charts/ScatterPlot.svelte';

  let availableMetrics = $state<MetricAvailable[]>([]);
  let metric1Type = $state('StepCount');
  let metric2Type = $state('HeartRate');
  let metric1Data = $state<MetricDataPoint[]>([]);
  let metric2Data = $state<MetricDataPoint[]>([]);
  let metric1Stats = $state<MetricResponse['stats'] | null>(null);
  let metric2Stats = $state<MetricResponse['stats'] | null>(null);
  let loading = $state(false);
  let initialLoading = $state(true);
  let error = $state('');

  // Load available metrics on mount
  $effect(() => {
    loadAvailableMetrics();
  });

  async function loadAvailableMetrics() {
    try {
      availableMetrics = await api.get<MetricAvailable[]>('/api/metrics/available');
    } catch {
      // Use default list
    } finally {
      initialLoading = false;
    }
  }

  // Reactively load data when metrics or date range changes
  $effect(() => {
    const _m1 = metric1Type;
    const _m2 = metric2Type;
    const _s = dateRange.startISO;
    const _e = dateRange.endISO;
    const _r = dateRange.resolution;
    if (!initialLoading) {
      loadComparisonData();
    }
  });

  async function loadComparisonData() {
    loading = true;
    error = '';

    const params = `?start=${dateRange.startISO}&end=${dateRange.endISO}&resolution=${dateRange.resolution}`;

    try {
      const [res1, res2] = await Promise.all([
        api.get<MetricResponse>(`/api/metrics/${metric1Type}${params}`),
        api.get<MetricResponse>(`/api/metrics/${metric2Type}${params}`),
      ]);
      metric1Data = res1.data;
      metric1Stats = res1.stats;
      metric2Data = res2.data;
      metric2Stats = res2.stats;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load metric data';
    } finally {
      loading = false;
    }
  }

  function getLabel(type: string): string {
    return METRIC_LABELS[type] ?? type.replace(/([A-Z])/g, ' $1').trim();
  }

  function getColor(type: string): string {
    return METRIC_COLORS[type] ?? '#10b981';
  }

  function getUnit(type: string): string {
    return METRIC_UNITS[type] ?? '';
  }

  // Align data points by date for scatter plot
  let alignedData = $derived.by(() => {
    const map1 = new Map<string, number>();
    const map2 = new Map<string, number>();

    for (const d of metric1Data) {
      const day = d.time.slice(0, 10);
      map1.set(day, d.value);
    }
    for (const d of metric2Data) {
      const day = d.time.slice(0, 10);
      map2.set(day, d.value);
    }

    const xVals: number[] = [];
    const yVals: number[] = [];

    for (const [day, val1] of map1) {
      const val2 = map2.get(day);
      if (val2 !== undefined) {
        xVals.push(val1);
        yVals.push(val2);
      }
    }

    return { xValues: xVals, yValues: yVals };
  });

  // Period comparison: this week vs last week
  let periodComparison = $derived.by(() => {
    const now = new Date();
    const oneWeekAgo = new Date(now);
    oneWeekAgo.setDate(now.getDate() - 7);
    const twoWeeksAgo = new Date(now);
    twoWeeksAgo.setDate(now.getDate() - 14);

    function avgInRange(data: MetricDataPoint[], start: Date, end: Date): number {
      const filtered = data.filter((d) => {
        const t = new Date(d.time);
        return t >= start && t <= end;
      });
      if (filtered.length === 0) return 0;
      return filtered.reduce((sum, d) => sum + d.value, 0) / filtered.length;
    }

    return {
      metric1: {
        thisWeek: avgInRange(metric1Data, oneWeekAgo, now),
        lastWeek: avgInRange(metric1Data, twoWeeksAgo, oneWeekAgo),
      },
      metric2: {
        thisWeek: avgInRange(metric2Data, oneWeekAgo, now),
        lastWeek: avgInRange(metric2Data, twoWeeksAgo, oneWeekAgo),
      },
    };
  });

  function pctChange(current: number, previous: number): string {
    if (previous === 0) return '--';
    const pct = ((current - previous) / previous) * 100;
    return `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`;
  }
</script>

<div class="space-y-6">
  <!-- Metric selectors -->
  <div class="bg-surface-800 rounded-xl border border-surface-700 p-5">
    <h3 class="text-sm font-semibold text-surface-300 mb-4">Compare Metrics</h3>
    <div class="flex flex-col sm:flex-row gap-4">
      <div class="flex-1">
        <label for="metric1" class="block text-xs text-surface-500 mb-1.5">Metric 1</label>
        <select
          id="metric1"
          bind:value={metric1Type}
          data-testid="trends-metric1-select"
          class="w-full appearance-none bg-surface-700 border border-surface-600 rounded-lg px-3 py-2.5
                 text-sm text-surface-200 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500
                 transition-colors cursor-pointer"
        >
          {#each availableMetrics as m}
            <option value={m.metric_type}>{getLabel(m.metric_type)}</option>
          {/each}
          {#if availableMetrics.length === 0}
            {#each Object.entries(METRIC_LABELS) as [value, label]}
              <option {value}>{label}</option>
            {/each}
          {/if}
        </select>
      </div>

      <div class="flex items-end pb-2">
        <span class="text-surface-500 text-sm font-medium">vs</span>
      </div>

      <div class="flex-1">
        <label for="metric2" class="block text-xs text-surface-500 mb-1.5">Metric 2</label>
        <select
          id="metric2"
          bind:value={metric2Type}
          data-testid="trends-metric2-select"
          class="w-full appearance-none bg-surface-700 border border-surface-600 rounded-lg px-3 py-2.5
                 text-sm text-surface-200 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500
                 transition-colors cursor-pointer"
        >
          {#each availableMetrics as m}
            <option value={m.metric_type}>{getLabel(m.metric_type)}</option>
          {/each}
          {#if availableMetrics.length === 0}
            {#each Object.entries(METRIC_LABELS) as [value, label]}
              <option {value}>{label}</option>
            {/each}
          {/if}
        </select>
      </div>
    </div>
  </div>

  {#if loading}
    <div class="space-y-6">
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 h-[350px] animate-pulse">
        <div class="w-full h-full bg-surface-700/50 rounded"></div>
      </div>
    </div>
  {:else if error}
    <div class="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400">{error}</p>
      <button
        class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm transition-colors"
        onclick={loadComparisonData}
      >
        Retry
      </button>
    </div>
  {:else}
    <!-- Dual-axis time series chart -->
    {#if metric1Data.length > 0 || metric2Data.length > 0}
      <div>
        <h3 class="text-sm font-semibold text-surface-300 mb-3">
          <span style="color: {getColor(metric1Type)}">{getLabel(metric1Type)}</span>
          <span class="text-surface-500"> vs </span>
          <span style="color: {getColor(metric2Type)}">{getLabel(metric2Type)}</span>
        </h3>
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-4" style="height: 350px;">
          <TimeSeriesChart
            data={metric1Data}
            label={getLabel(metric1Type)}
            color={getColor(metric1Type)}
            fill={false}
          />
        </div>
        {#if metric2Data.length > 0}
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-4 mt-4" style="height: 350px;">
            <TimeSeriesChart
              data={metric2Data}
              label={getLabel(metric2Type)}
              color={getColor(metric2Type)}
              fill={false}
            />
          </div>
        {/if}
      </div>
    {/if}

    <!-- Scatter plot correlation -->
    {#if alignedData.xValues.length > 2}
      <div>
        <h3 class="text-sm font-semibold text-surface-300 mb-3">Correlation</h3>
        <div style="height: 300px;" data-testid="trends-scatter-chart">
          <ScatterPlot
            xValues={alignedData.xValues}
            yValues={alignedData.yValues}
            xLabel={getLabel(metric1Type)}
            yLabel={getLabel(metric2Type)}
            color="#10b981"
            xUnit={getUnit(metric1Type)}
            yUnit={getUnit(metric2Type)}
          />
        </div>
        <p class="text-xs text-surface-500 mt-2 text-center">
          {alignedData.xValues.length} overlapping data points
        </p>
      </div>
    {/if}

    <!-- Period comparison -->
    <div>
      <h3 class="text-sm font-semibold text-surface-300 mb-3">This Week vs Last Week</h3>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <!-- Metric 1 comparison -->
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-5">
          <div class="flex items-center gap-2 mb-3">
            <div class="w-2.5 h-2.5 rounded-full" style="background-color: {getColor(metric1Type)}"></div>
            <span class="text-sm font-medium text-surface-200">{getLabel(metric1Type)}</span>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <p class="text-xs text-surface-500">This Week</p>
              <p class="text-lg font-semibold text-surface-100">
                {formatMetricValue(periodComparison.metric1.thisWeek, getUnit(metric1Type))}
              </p>
            </div>
            <div>
              <p class="text-xs text-surface-500">Last Week</p>
              <p class="text-lg font-semibold text-surface-100">
                {formatMetricValue(periodComparison.metric1.lastWeek, getUnit(metric1Type))}
              </p>
            </div>
          </div>
          <p class="text-sm mt-2 {periodComparison.metric1.thisWeek >= periodComparison.metric1.lastWeek ? 'text-green-400' : 'text-red-400'}">
            {pctChange(periodComparison.metric1.thisWeek, periodComparison.metric1.lastWeek)}
          </p>
        </div>

        <!-- Metric 2 comparison -->
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-5">
          <div class="flex items-center gap-2 mb-3">
            <div class="w-2.5 h-2.5 rounded-full" style="background-color: {getColor(metric2Type)}"></div>
            <span class="text-sm font-medium text-surface-200">{getLabel(metric2Type)}</span>
          </div>
          <div class="grid grid-cols-2 gap-4">
            <div>
              <p class="text-xs text-surface-500">This Week</p>
              <p class="text-lg font-semibold text-surface-100">
                {formatMetricValue(periodComparison.metric2.thisWeek, getUnit(metric2Type))}
              </p>
            </div>
            <div>
              <p class="text-xs text-surface-500">Last Week</p>
              <p class="text-lg font-semibold text-surface-100">
                {formatMetricValue(periodComparison.metric2.lastWeek, getUnit(metric2Type))}
              </p>
            </div>
          </div>
          <p class="text-sm mt-2 {periodComparison.metric2.thisWeek >= periodComparison.metric2.lastWeek ? 'text-green-400' : 'text-red-400'}">
            {pctChange(periodComparison.metric2.thisWeek, periodComparison.metric2.lastWeek)}
          </p>
        </div>
      </div>
    </div>

    <!-- Stats summary -->
    {#if metric1Stats && metric2Stats}
      <div>
        <h3 class="text-sm font-semibold text-surface-300 mb-3">Statistics</h3>
        <div class="bg-surface-800 rounded-xl border border-surface-700 overflow-hidden">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-surface-700">
                <th class="text-left px-4 py-3 text-surface-500 font-medium">Stat</th>
                <th class="text-right px-4 py-3 font-medium" style="color: {getColor(metric1Type)}">{getLabel(metric1Type)}</th>
                <th class="text-right px-4 py-3 font-medium" style="color: {getColor(metric2Type)}">{getLabel(metric2Type)}</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-surface-700">
              <tr>
                <td class="px-4 py-3 text-surface-400">Average</td>
                <td class="px-4 py-3 text-right text-surface-200">{formatMetricValue(metric1Stats.avg, getUnit(metric1Type))}</td>
                <td class="px-4 py-3 text-right text-surface-200">{formatMetricValue(metric2Stats.avg, getUnit(metric2Type))}</td>
              </tr>
              <tr>
                <td class="px-4 py-3 text-surface-400">Min</td>
                <td class="px-4 py-3 text-right text-surface-200">{formatMetricValue(metric1Stats.min, getUnit(metric1Type))}</td>
                <td class="px-4 py-3 text-right text-surface-200">{formatMetricValue(metric2Stats.min, getUnit(metric2Type))}</td>
              </tr>
              <tr>
                <td class="px-4 py-3 text-surface-400">Max</td>
                <td class="px-4 py-3 text-right text-surface-200">{formatMetricValue(metric1Stats.max, getUnit(metric1Type))}</td>
                <td class="px-4 py-3 text-right text-surface-200">{formatMetricValue(metric2Stats.max, getUnit(metric2Type))}</td>
              </tr>
              <tr>
                <td class="px-4 py-3 text-surface-400">Data Points</td>
                <td class="px-4 py-3 text-right text-surface-200">{formatNumber(metric1Stats.count)}</td>
                <td class="px-4 py-3 text-right text-surface-200">{formatNumber(metric2Stats.count)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    {/if}
  {/if}
</div>
