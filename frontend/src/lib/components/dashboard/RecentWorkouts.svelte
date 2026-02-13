<script lang="ts">
  import { api } from '$lib/api';
  import type { WorkoutSummary } from '$lib/types';
  import { formatDuration, formatDistance, formatEnergy } from '$lib/utils/format';

  interface Props {
    start?: string;
    end?: string;
  }

  let { start, end }: Props = $props();

  let workouts = $state<WorkoutSummary[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  $effect(() => {
    const _s = start;
    const _e = end;
    loadWorkouts();
  });

  async function loadWorkouts() {
    loading = true;
    error = null;
    try {
      let url = '/api/workouts?limit=5';
      if (start) url += `&start=${start}`;
      if (end) url += `&end=${end}`;
      workouts = await api.get<WorkoutSummary[]>(url);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load workouts';
    } finally {
      loading = false;
    }
  }

  function formatDate(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
    });
  }

  function activityIcon(type: string): string {
    const t = type.toLowerCase();
    if (t.includes('run')) return 'M13 10V3L4 14h7v7l9-11h-7z';
    if (t.includes('walk')) return 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6';
    if (t.includes('cycl') || t.includes('bik')) return 'M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2';
    if (t.includes('swim')) return 'M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21';
    if (t.includes('yoga')) return 'M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z';
    if (t.includes('hik')) return 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6';
    // Default exercise icon
    return 'M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z';
  }

  function activityLabel(type: string): string {
    // Convert snake_case or camelCase to readable
    return type
      .replace(/([A-Z])/g, ' $1')
      .replace(/_/g, ' ')
      .replace(/^./, (s) => s.toUpperCase())
      .trim();
  }
</script>

<div class="rounded-xl bg-surface-800 border border-surface-700/50 overflow-hidden">
  <div class="px-4 py-3 border-b border-surface-700/50">
    <h3 class="text-sm font-semibold text-surface-200">Recent Workouts</h3>
  </div>

  {#if loading}
    <div class="divide-y divide-surface-700/50">
      {#each Array(5) as _}
        <div class="px-4 py-3 flex items-center gap-3 animate-pulse">
          <div class="w-9 h-9 rounded-lg bg-surface-700"></div>
          <div class="flex-1">
            <div class="h-4 w-24 bg-surface-700 rounded mb-1"></div>
            <div class="h-3 w-16 bg-surface-700 rounded"></div>
          </div>
          <div class="text-right">
            <div class="h-4 w-12 bg-surface-700 rounded mb-1"></div>
            <div class="h-3 w-16 bg-surface-700 rounded"></div>
          </div>
        </div>
      {/each}
    </div>
  {:else if error}
    <div class="p-6 text-center">
      <p class="text-red-400 text-sm">{error}</p>
      <button
        onclick={loadWorkouts}
        class="mt-2 text-xs text-primary-400 hover:text-primary-300 underline"
      >
        Retry
      </button>
    </div>
  {:else if workouts.length === 0}
    <div class="p-6 text-center">
      <p class="text-surface-500 text-sm">No workouts recorded yet</p>
    </div>
  {:else}
    <div class="divide-y divide-surface-700/50">
      {#each workouts as workout}
        <a
          href="/workouts/{workout.id}"
          class="px-4 py-3 flex items-center gap-3 hover:bg-surface-700/50 transition-colors"
        >
          <div class="w-9 h-9 rounded-lg bg-[var(--color-workout)]/15 flex items-center justify-center flex-shrink-0">
            <svg class="w-4.5 h-4.5 text-[var(--color-workout)]" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d={activityIcon(workout.activity_type)} />
            </svg>
          </div>

          <div class="flex-1 min-w-0">
            <p class="text-sm font-medium text-surface-200 truncate">
              {activityLabel(workout.activity_type)}
            </p>
            <p class="text-xs text-surface-500">{formatDate(workout.time)}</p>
          </div>

          <div class="text-right flex-shrink-0">
            <p class="text-sm font-medium text-surface-300">
              {formatDuration(workout.duration_sec)}
            </p>
            <div class="flex items-center gap-2 text-xs text-surface-500">
              {#if workout.total_distance_m > 0}
                <span>{formatDistance(workout.total_distance_m)}</span>
              {/if}
              {#if workout.total_energy_kj > 0}
                <span>{formatEnergy(workout.total_energy_kj)}</span>
              {/if}
            </div>
          </div>
        </a>
      {/each}
    </div>

    <div class="px-4 py-2.5 border-t border-surface-700/50">
      <a href="/workouts" class="text-xs text-primary-400 hover:text-primary-300 font-medium">
        View all workouts
      </a>
    </div>
  {/if}
</div>
