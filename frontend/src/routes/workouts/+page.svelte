<script lang="ts">
  import { api } from '$lib/api';
  import type { WorkoutSummary } from '$lib/types';
  import { WORKOUT_LABELS } from '$lib/utils/constants';
  import { formatDate, formatDuration, formatDistance, formatNumber, formatEnergy } from '$lib/utils/format';
  import { dateRange } from '$lib/stores/date-range.svelte';

  let workouts = $state<WorkoutSummary[]>([]);
  let loading = $state(true);
  let loadingMore = $state(false);
  let error = $state('');
  let hasMore = $state(true);
  let offset = $state(0);
  let selectedType = $state('');
  const limit = 20;

  const WORKOUT_ICONS: Record<string, string> = {
    Running: '\u{1F3C3}',
    Walking: '\u{1F6B6}',
    Cycling: '\u{1F6B4}',
    Swimming: '\u{1F3CA}',
    Hiking: '\u{26F0}',
    Yoga: '\u{1F9D8}',
    FunctionalStrengthTraining: '\u{1F4AA}',
    HighIntensityIntervalTraining: '\u{1F525}',
    TraditionalStrengthTraining: '\u{1F3CB}',
    Elliptical: '\u{1F6B2}',
    Rowing: '\u{1F6A3}',
    Dance: '\u{1F483}',
    Tennis: '\u{1F3BE}',
    Soccer: '\u{26BD}',
    Basketball: '\u{1F3C0}',
  };

  $effect(() => {
    const _t = selectedType;
    const _s = dateRange.startISO;
    const _e = dateRange.endISO;
    offset = 0;
    workouts = [];
    hasMore = true;
    loadWorkouts(true);
  });

  async function loadWorkouts(reset = false) {
    if (reset) {
      loading = true;
    } else {
      loadingMore = true;
    }
    error = '';

    try {
      let url = `/api/workouts?limit=${limit}&offset=${reset ? 0 : offset}&start=${dateRange.startISO}&end=${dateRange.endISO}`;
      if (selectedType) {
        url += `&activity_type=${selectedType}`;
      }
      const result = await api.get<WorkoutSummary[]>(url);

      if (reset) {
        workouts = result;
        offset = result.length;
      } else {
        workouts = [...workouts, ...result];
        offset += result.length;
      }

      hasMore = result.length === limit;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load workouts';
    } finally {
      loading = false;
      loadingMore = false;
    }
  }

  function getLabel(type: string): string {
    return WORKOUT_LABELS[type] ?? type.replace(/([A-Z])/g, ' $1').trim();
  }

  function getIcon(type: string): string {
    return WORKOUT_ICONS[type] ?? '\u{1F3C6}';
  }
</script>

<div class="space-y-6">
  <!-- Filter bar -->
  <div class="flex flex-col sm:flex-row sm:items-center gap-3">
    <div class="relative">
      <select
        bind:value={selectedType}
        class="appearance-none bg-surface-800 border border-surface-700 rounded-lg px-4 py-2.5 pr-8
               text-sm text-surface-200 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500
               transition-colors cursor-pointer"
      >
        <option value="">All Activity Types</option>
        {#each Object.entries(WORKOUT_LABELS) as [value, label]}
          <option {value}>{label}</option>
        {/each}
      </select>
      <svg class="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
      </svg>
    </div>

    {#if workouts.length > 0}
      <p class="text-sm text-surface-500">
        Showing {workouts.length} workout{workouts.length !== 1 ? 's' : ''}
      </p>
    {/if}
  </div>

  {#if loading}
    <!-- Loading skeleton -->
    <div class="space-y-3">
      {#each Array(6) as _}
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-4 animate-pulse">
          <div class="flex items-center gap-4">
            <div class="w-10 h-10 bg-surface-700 rounded-lg"></div>
            <div class="flex-1 space-y-2">
              <div class="w-32 h-4 bg-surface-700 rounded"></div>
              <div class="w-48 h-3 bg-surface-700 rounded"></div>
            </div>
            <div class="flex gap-6">
              <div class="w-16 h-4 bg-surface-700 rounded"></div>
              <div class="w-16 h-4 bg-surface-700 rounded"></div>
              <div class="w-16 h-4 bg-surface-700 rounded"></div>
            </div>
          </div>
        </div>
      {/each}
    </div>
  {:else if error}
    <div class="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400">{error}</p>
      <button
        class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm transition-colors"
        onclick={() => loadWorkouts(true)}
      >
        Retry
      </button>
    </div>
  {:else if workouts.length === 0}
    <div class="p-12 text-center bg-surface-800 rounded-xl border border-surface-700">
      <svg class="w-12 h-12 text-surface-600 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
      <p class="text-surface-400">No workouts found.</p>
    </div>
  {:else}
    <div class="space-y-3">
      {#each workouts as workout}
        <a
          href="/workouts/{workout.id}"
          class="group flex items-center gap-4 bg-surface-800 rounded-xl border border-surface-700 p-4
                 hover:border-surface-600 hover:bg-surface-800/80 transition-all"
        >
          <!-- Activity icon -->
          <div class="w-10 h-10 rounded-lg bg-surface-700 flex items-center justify-center text-lg shrink-0">
            {getIcon(workout.activity_type)}
          </div>

          <!-- Info -->
          <div class="flex-1 min-w-0">
            <h3 class="text-sm font-medium text-surface-200 group-hover:text-surface-100 transition-colors">
              {getLabel(workout.activity_type)}
            </h3>
            <p class="text-xs text-surface-500 mt-0.5">
              {formatDate(workout.time)}
            </p>
          </div>

          <!-- Stats -->
          <div class="flex items-center gap-4 sm:gap-6 text-right shrink-0">
            <div>
              <p class="text-xs text-surface-500">Duration</p>
              <p class="text-sm font-medium text-surface-200">
                {formatDuration(workout.duration_sec)}
              </p>
            </div>

            {#if workout.total_distance_m > 0}
              <div class="hidden sm:block">
                <p class="text-xs text-surface-500">Distance</p>
                <p class="text-sm font-medium text-surface-200">
                  {formatDistance(workout.total_distance_m)}
                </p>
              </div>
            {/if}

            {#if workout.total_energy_kj > 0}
              <div class="hidden sm:block">
                <p class="text-xs text-surface-500">Energy</p>
                <p class="text-sm font-medium text-surface-200">
                  {formatEnergy(workout.total_energy_kj)}
                </p>
              </div>
            {/if}

            <svg class="w-4 h-4 text-surface-600 group-hover:text-surface-400 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
            </svg>
          </div>
        </a>
      {/each}
    </div>

    <!-- Load more -->
    {#if hasMore}
      <div class="flex justify-center">
        <button
          class="px-6 py-2.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 hover:border-surface-600
                 text-sm font-medium text-surface-300 rounded-lg transition-colors
                 disabled:opacity-50 disabled:cursor-not-allowed"
          disabled={loadingMore}
          onclick={() => loadWorkouts(false)}
        >
          {#if loadingMore}
            <span class="flex items-center gap-2">
              <div class="w-4 h-4 border-2 border-surface-400 border-t-transparent rounded-full animate-spin"></div>
              Loading...
            </span>
          {:else}
            Load More
          {/if}
        </button>
      </div>
    {/if}
  {/if}
</div>
