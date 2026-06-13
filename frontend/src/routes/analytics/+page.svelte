<script lang="ts">
  // Training analytics (Progress) — the phone-first view that ships in every
  // competitor app: a muscle body-map heatmap (Recovery freshness or trailing
  // weekly volume) plus per-Exercise estimated-1RM trend charts. Reads the
  // /api/analytics aggregates the backend computes from logged Sets; no extra
  // full table scans.

  import { api } from '$lib/api';
  import type {
    E1rmTrendResponse,
    RecoveryResponse,
    TrainedExercise,
    VolumeResponse,
  } from '$lib/types';
  import { muscleLabel, recoveryColor } from '$lib/muscle-heat';
  import { formatNumber } from '$lib/utils/format';
  import BodyHeatmap from '$lib/components/charts/BodyHeatmap.svelte';
  import TimeSeriesChart from '$lib/components/charts/TimeSeriesChart.svelte';

  type HeatMode = 'recovery' | 'volume';

  let mode = $state<HeatMode>('recovery');
  let volumeWeeks = $state(4);

  let recovery = $state<RecoveryResponse | null>(null);
  let volume = $state<VolumeResponse | null>(null);
  let loading = $state(true);
  let error = $state('');

  // --- e1RM trend ---
  let trained = $state<TrainedExercise[]>([]);
  let selectedExercise = $state('');
  let trend = $state<E1rmTrendResponse | null>(null);
  let trendLoading = $state(false);

  // Load the heatmap data (both scales) + the trained-exercise list once.
  $effect(() => {
    loadAnalytics();
  });

  // Reload weekly volume when the window changes (recovery is window-independent).
  $effect(() => {
    const _w = volumeWeeks;
    if (!loading) loadVolume();
  });

  // Fetch the e1RM trend whenever the picked Exercise changes.
  $effect(() => {
    const _ex = selectedExercise;
    if (selectedExercise) loadTrend();
    else trend = null;
  });

  async function loadAnalytics() {
    loading = true;
    error = '';
    try {
      const [rec, vol, ex] = await Promise.all([
        api.get<RecoveryResponse>('/api/analytics/recovery'),
        api.get<VolumeResponse>(`/api/analytics/volume?weeks=${volumeWeeks}`),
        api.get<TrainedExercise[]>('/api/analytics/exercises'),
      ]);
      recovery = rec;
      volume = vol;
      trained = ex;
      if (!selectedExercise && ex.length > 0) selectedExercise = ex[0].id;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load analytics';
    } finally {
      loading = false;
    }
  }

  async function loadVolume() {
    try {
      volume = await api.get<VolumeResponse>(`/api/analytics/volume?weeks=${volumeWeeks}`);
    } catch {
      // Keep the last good volume on a transient error; recovery view still works.
    }
  }

  async function loadTrend() {
    trendLoading = true;
    try {
      trend = await api.get<E1rmTrendResponse>(
        `/api/analytics/e1rm-trend?exercise_id=${selectedExercise}`,
      );
    } catch {
      trend = null;
    } finally {
      trendLoading = false;
    }
  }

  // muscle → value map the body-map colours by. Recovery: the 0–100 score.
  // Volume: total volume-load summed across roles per muscle (so a muscle hit as
  // both primary and secondary reads its combined work).
  let heatValues = $derived.by(() => {
    const map = new Map<string, number>();
    if (mode === 'recovery') {
      for (const m of recovery?.muscles ?? []) map.set(m.muscle, m.recovery);
    } else {
      for (const m of volume?.muscles ?? []) {
        map.set(m.muscle, (map.get(m.muscle) ?? 0) + m.volume_load);
      }
    }
    return map;
  });

  // The volume table: one row per muscle (combined sets + load), busiest first.
  let volumeRows = $derived.by(() => {
    const agg = new Map<string, { sets: number; load: number }>();
    for (const m of volume?.muscles ?? []) {
      const cur = agg.get(m.muscle) ?? { sets: 0, load: 0 };
      cur.sets += m.set_count;
      cur.load += m.volume_load;
      agg.set(m.muscle, cur);
    }
    return [...agg.entries()]
      .map(([muscle, v]) => ({ muscle, ...v }))
      .sort((a, b) => b.load - a.load);
  });

  // Most-fatigued muscles (lowest recovery), for the "needs rest" callout.
  let mostFatigued = $derived.by(() =>
    [...(recovery?.muscles ?? [])]
      .filter((m) => m.recovery < 100)
      .sort((a, b) => a.recovery - b.recovery)
      .slice(0, 5),
  );

  // The trend chart wants {time, value}[]; map e1RM points onto it.
  let trendData = $derived(
    (trend?.points ?? []).map((p) => ({ time: p.time, value: p.e1rm })),
  );

  let selectedName = $derived(
    trained.find((e) => e.id === selectedExercise)?.name ?? 'Exercise',
  );
</script>

<svelte:head><title>Progress · Analytics</title></svelte:head>

<div class="space-y-6">
  <div>
    <h1 class="text-xl font-semibold text-surface-100">Progress</h1>
    <p class="text-sm text-surface-500">Muscle recovery, training volume, and strength trends.</p>
  </div>

  {#if loading}
    <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 h-[420px] animate-pulse">
      <div class="w-full h-full bg-surface-700/50 rounded"></div>
    </div>
  {:else if error}
    <div class="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400">{error}</p>
      <button
        class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm transition-colors"
        onclick={loadAnalytics}
      >
        Retry
      </button>
    </div>
  {:else}
    <!-- Muscle heatmap -->
    <section class="bg-surface-800 rounded-xl border border-surface-700 p-4">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-surface-300">Muscle map</h2>
        <!-- Recovery / Volume toggle -->
        <div class="inline-flex rounded-lg bg-surface-700 p-0.5 text-xs">
          {#each ['recovery', 'volume'] as const as m}
            <button
              class="px-3 py-1.5 rounded-md transition-colors capitalize {mode === m
                ? 'bg-accent-600 text-white'
                : 'text-surface-300 hover:text-surface-100'}"
              onclick={() => (mode = m)}
            >
              {m}
            </button>
          {/each}
        </div>
      </div>

      <BodyHeatmap values={heatValues} {mode} />

      <!-- Legend -->
      <div class="mt-4 flex items-center justify-center gap-3 text-xs text-surface-400">
        {#if mode === 'recovery'}
          <span>Fatigued</span>
          <div
            class="h-2 w-32 rounded-full"
            style="background: linear-gradient(to right, {recoveryColor(0)}, {recoveryColor(50)}, {recoveryColor(100)});"
          ></div>
          <span>Fresh</span>
        {:else}
          <span>Less</span>
          <div
            class="h-2 w-32 rounded-full"
            style="background: linear-gradient(to right, rgba(16,185,129,0.2), rgba(16,185,129,1));"
          ></div>
          <span>More volume</span>
        {/if}
      </div>

      {#if mode === 'recovery' && recovery}
        <p class="mt-3 text-center text-xs text-surface-500">
          From training load only · {recovery.half_life_hours}h fatigue half-life
        </p>
      {/if}
    </section>

    <!-- Recovery callout: muscles that need rest -->
    {#if mode === 'recovery' && mostFatigued.length > 0}
      <section>
        <h2 class="text-sm font-semibold text-surface-300 mb-3">Most fatigued</h2>
        <div class="space-y-2">
          {#each mostFatigued as m}
            <div class="bg-surface-800 rounded-lg border border-surface-700 p-3">
              <div class="flex items-center justify-between mb-1.5 text-sm">
                <span class="text-surface-200">{muscleLabel(m.muscle)}</span>
                <span class="text-surface-400">{Math.round(m.recovery)}%</span>
              </div>
              <div class="h-1.5 rounded-full bg-surface-700 overflow-hidden">
                <div
                  class="h-full rounded-full transition-all duration-500"
                  style="width: {m.recovery}%; background-color: {recoveryColor(m.recovery)};"
                ></div>
              </div>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    <!-- Weekly volume -->
    {#if mode === 'volume'}
      <section>
        <div class="flex items-center justify-between mb-3">
          <h2 class="text-sm font-semibold text-surface-300">Volume by muscle</h2>
          <select
            bind:value={volumeWeeks}
            class="appearance-none bg-surface-700 border border-surface-600 rounded-lg px-3 py-1.5
                   text-xs text-surface-200 focus:outline-none focus:border-primary-500 cursor-pointer"
          >
            <option value={1}>Last week</option>
            <option value={4}>Last 4 weeks</option>
            <option value={8}>Last 8 weeks</option>
            <option value={12}>Last 12 weeks</option>
          </select>
        </div>
        {#if volumeRows.length === 0}
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 text-center text-sm text-surface-500">
            No logged sets in this window.
          </div>
        {:else}
          <div class="bg-surface-800 rounded-xl border border-surface-700 overflow-hidden">
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b border-surface-700 text-surface-500">
                  <th class="text-left px-4 py-2.5 font-medium">Muscle</th>
                  <th class="text-right px-4 py-2.5 font-medium">Sets</th>
                  <th class="text-right px-4 py-2.5 font-medium">Volume (kg·reps)</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-surface-700">
                {#each volumeRows as r}
                  <tr>
                    <td class="px-4 py-2.5 text-surface-200">{muscleLabel(r.muscle)}</td>
                    <td class="px-4 py-2.5 text-right text-surface-300">{r.sets}</td>
                    <td class="px-4 py-2.5 text-right text-surface-300">{formatNumber(r.load)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </section>
    {/if}

    <!-- e1RM trend -->
    <section>
      <h2 class="text-sm font-semibold text-surface-300 mb-3">Estimated 1RM trend</h2>
      {#if trained.length === 0}
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 text-center text-sm text-surface-500">
          Log some sets to see your strength trends.
        </div>
      {:else}
        <select
          bind:value={selectedExercise}
          class="w-full mb-3 appearance-none bg-surface-700 border border-surface-600 rounded-lg px-3 py-2.5
                 text-sm text-surface-200 focus:outline-none focus:border-primary-500 cursor-pointer"
        >
          {#each trained as ex}
            <option value={ex.id}>{ex.name}</option>
          {/each}
        </select>

        {#if trendLoading}
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-4 h-[300px] animate-pulse">
            <div class="w-full h-full bg-surface-700/50 rounded"></div>
          </div>
        {:else if trendData.length === 0}
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 text-center text-sm text-surface-500">
            No normal sets logged for {selectedName} yet.
          </div>
        {:else}
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
            {#if trend?.best_e1rm}
              <p class="text-xs text-surface-500 mb-2">
                Best: <span class="text-primary-400 font-medium">{formatNumber(trend.best_e1rm, 1)} kg</span>
                · {trendData.length} set{trendData.length === 1 ? '' : 's'}
              </p>
            {/if}
            <div style="height: 300px;">
              <TimeSeriesChart data={trendData} label={`${selectedName} e1RM (kg)`} color="#10b981" fill={true} />
            </div>
          </div>
        {/if}
      {/if}
    </section>
  {/if}
</div>
