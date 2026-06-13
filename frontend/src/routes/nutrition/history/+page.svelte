<script lang="ts">
  import { api } from '$lib/api';
  import BarChart from '$lib/components/charts/BarChart.svelte';
  import {
    historyToSeries,
    formatMacro,
    type DiaryDaySummary,
    type MacroKey,
  } from '$lib/nutrition';

  // Nutrition history (#21): calories and macros over time, reusing the existing
  // BarChart (it aggregates daily by date). A simple trailing-window selector
  // and a metric toggle (calories / protein / carbs / fat). Mobile-first.

  const WINDOWS = [
    { days: 7, label: '7d' },
    { days: 14, label: '14d' },
    { days: 30, label: '30d' },
    { days: 90, label: '90d' },
  ];
  const METRICS: { key: MacroKey; label: string; color: string }[] = [
    { key: 'calories', label: 'Calories', color: '#f59e0b' },
    { key: 'protein_g', label: 'Protein', color: '#60a5fa' },
    { key: 'carbs_g', label: 'Carbs', color: '#34d399' },
    { key: 'fat_g', label: 'Fat', color: '#fbbf24' },
  ];

  let windowDays = $state(14);
  let metric = $state<MacroKey>('calories');
  let history = $state<DiaryDaySummary[]>([]);
  let loading = $state(true);
  let error = $state('');

  function isoDaysAgo(days: number): string {
    const d = new Date();
    d.setDate(d.getDate() - days);
    return d.toISOString().slice(0, 10);
  }
  function todayIso(): string {
    return new Date().toISOString().slice(0, 10);
  }

  $effect(() => {
    const _w = windowDays;
    load();
  });

  async function load() {
    loading = true;
    error = '';
    try {
      const start = isoDaysAgo(windowDays - 1);
      const end = todayIso();
      history = await api.get<DiaryDaySummary[]>(
        `/api/nutrition/history?start=${start}&end=${end}`,
      );
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load history';
    } finally {
      loading = false;
    }
  }

  let series = $derived(historyToSeries(history, metric));
  let activeMetric = $derived(METRICS.find((m) => m.key === metric)!);

  // Average over the logged days (days with no entries don't appear).
  let average = $derived(
    history.length
      ? history.reduce((s, d) => s + d.total[metric], 0) / history.length
      : 0,
  );
</script>

<div class="space-y-4 pb-24">
  <div class="flex items-center gap-3">
    <a href="/nutrition" class="p-1.5 -ml-1.5 text-surface-400 hover:text-surface-200" aria-label="Back to diary">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
      </svg>
    </a>
    <h1 class="text-2xl font-semibold text-surface-100">History</h1>
  </div>

  <!-- Metric toggle -->
  <div class="flex flex-wrap gap-2">
    {#each METRICS as m}
      <button
        onclick={() => (metric = m.key)}
        class="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors border
               {metric === m.key
          ? 'bg-primary-500/20 border-primary-500/60 text-primary-200'
          : 'bg-surface-800 border-surface-700 text-surface-400 hover:text-surface-200'}"
      >
        {m.label}
      </button>
    {/each}
  </div>

  <!-- Window selector -->
  <div class="flex gap-2">
    {#each WINDOWS as w}
      <button
        onclick={() => (windowDays = w.days)}
        class="px-3 py-1 rounded-md text-xs font-medium transition-colors
               {windowDays === w.days
          ? 'bg-surface-700 text-surface-100'
          : 'bg-surface-800 text-surface-500 hover:text-surface-300'}"
      >
        {w.label}
      </button>
    {/each}
  </div>

  {#if error}
    <div class="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400 text-sm">{error}</p>
      <button class="mt-2 px-4 py-1.5 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm" onclick={load}>Retry</button>
    </div>
  {:else if loading && history.length === 0}
    <div class="h-64 bg-surface-800 rounded-xl border border-surface-700 animate-pulse"></div>
  {:else if history.length === 0}
    <div class="p-12 text-center bg-surface-800 rounded-xl border border-surface-700">
      <p class="text-surface-400 text-sm">No diary entries in this window yet.</p>
      <a href="/nutrition" class="mt-3 inline-block px-4 py-2 bg-primary-500/15 hover:bg-primary-500/25 text-primary-300 rounded-lg text-sm">
        Log something
      </a>
    </div>
  {:else}
    <!-- Average summary -->
    <div class="flex items-baseline justify-between bg-surface-800 rounded-xl border border-surface-700 px-4 py-3">
      <p class="text-xs uppercase tracking-wide text-surface-500">
        Daily average ({history.length} logged day{history.length !== 1 ? 's' : ''})
      </p>
      <p class="text-lg font-bold text-surface-100">
        {formatMacro(average, metric)}{metric === 'calories' ? ' kcal' : ''}
      </p>
    </div>

    <!-- Chart (BarChart aggregates by day from {time, value}). -->
    <div class="h-64">
      <BarChart data={series} label={activeMetric.label} color={activeMetric.color} />
    </div>
  {/if}
</div>
