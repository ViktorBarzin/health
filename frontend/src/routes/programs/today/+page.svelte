<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { muscleLabel } from '$lib/muscle-heat';
  import type { SessionDetail, TodayRecommendationResponse } from '$lib/types';
  import { formatWeight } from '$lib/utils/format';

  // Today's workout (#13, ADR-0004): drawn from the active Program's next due day
  // (its slots filled via the Progression core, constrained by the Gym Profile),
  // or freestyle when no Program is active. Starting it instantiates a Session
  // pre-filled with the target Sets — the same #11 instantiate path. Mobile-first.
  let today = $state<TodayRecommendationResponse | null>(null);
  let loading = $state(true);
  let error = $state('');
  let starting = $state(false);

  $effect(() => {
    load();
  });

  async function load() {
    loading = true;
    error = '';
    try {
      today = await api.get<TodayRecommendationResponse>('/api/recommendations/today');
    } catch (err) {
      error = err instanceof Error ? err.message : "Failed to load today's workout";
    } finally {
      loading = false;
    }
  }

  async function start() {
    if (starting) return;
    starting = true;
    error = '';
    try {
      const created = await api.post<SessionDetail>('/api/recommendations/today/start', {});
      await goto(`/sessions/${created.id}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to start workout';
      starting = false;
    }
  }

  let exercises = $derived(today?.exercises ?? []);
  let isEmpty = $derived(!loading && exercises.length === 0);
  let ctx = $derived(today?.program ?? null);
</script>

<div class="space-y-4 pb-28">
  <div class="flex items-center gap-3">
    <a
      href="/programs"
      class="shrink-0 p-2 -ml-2 rounded-lg text-surface-400 hover:text-surface-200 hover:bg-surface-800 transition-colors"
      aria-label="Back to Programs"
    >
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
      </svg>
    </a>
    <div class="min-w-0">
      <h1 class="text-2xl font-semibold text-surface-100">Today's workout</h1>
      {#if ctx}
        <p class="text-xs text-surface-500 truncate">
          {ctx.program_name} · {ctx.day_name} · Week {ctx.week} of {ctx.total_weeks}
        </p>
      {:else}
        <p class="text-xs text-surface-500">Freestyle — built from your recent training.</p>
      {/if}
    </div>
  </div>

  {#if ctx?.is_deload}
    <div class="px-4 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30">
      <p class="text-xs font-medium text-amber-300">
        Deload week — reduced volume to recover. Take it easy and let fatigue clear.
      </p>
    </div>
  {/if}

  {#if error}
    <div class="p-4 rounded-xl bg-red-500/10 border border-red-500/30">
      <p class="text-sm text-red-400">{error}</p>
      <button onclick={load} class="mt-2 text-xs font-medium text-red-300 underline underline-offset-2">
        Try again
      </button>
    </div>
  {/if}

  {#if loading}
    <div class="space-y-2">
      {#each Array(4) as _}
        <div class="h-24 bg-surface-800 rounded-xl border border-surface-700 animate-pulse"></div>
      {/each}
    </div>
  {:else if isEmpty}
    <div class="p-10 text-center bg-surface-800 rounded-xl border border-surface-700">
      <p class="text-surface-300 text-sm font-medium">Nothing to prescribe yet</p>
      <p class="mt-1 text-surface-500 text-xs max-w-xs mx-auto">
        {#if ctx}
          The Gym Profile has no equipment for today's muscles, or there are no
          matching Exercises. Check your equipment in Settings.
        {:else}
          Log a few Sessions, or pick a Program, and your next workout appears here.
        {/if}
      </p>
      <a
        href="/programs"
        class="inline-block mt-4 px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold transition-colors"
      >
        Browse programs
      </a>
    </div>
  {:else}
    <ul class="space-y-2">
      {#each exercises as ex (ex.exercise_id)}
        <li class="p-4 rounded-xl bg-surface-800 border border-surface-700">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="text-sm font-semibold text-surface-100 truncate">{ex.name}</p>
              {#if ex.primary_muscles.length > 0}
                <p class="mt-0.5 text-xs text-surface-500 truncate">
                  {ex.primary_muscles.map(muscleLabel).join(', ')}
                </p>
              {/if}
            </div>
            <div class="shrink-0 text-right">
              <p class="text-sm font-semibold text-primary-300 tabular-nums">
                {ex.target_sets} × {ex.target_reps}
              </p>
              <p class="text-xs text-surface-400 tabular-nums">
                {#if ex.is_starting_point}
                  pick a weight
                {:else}
                  {formatWeight(ex.target_weight_kg)} kg
                {/if}
              </p>
            </div>
          </div>
        </li>
      {/each}
    </ul>
    <p class="text-center text-xs text-surface-600">
      You can change any weight, reps, or set once you start — your edits always win.
    </p>
  {/if}
</div>

<!-- Sticky start bar -->
{#if !loading && !isEmpty}
  <div class="fixed inset-x-0 bottom-16 sm:bottom-0 px-4 pb-3 pt-2 bg-gradient-to-t from-surface-900 via-surface-900/95 to-transparent">
    <div class="max-w-2xl mx-auto">
      <button
        onclick={start}
        disabled={starting}
        class="w-full flex items-center justify-center gap-2 py-3.5 rounded-2xl bg-primary-500 hover:bg-primary-600 text-white font-semibold text-base transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-primary-500/20"
      >
        {#if starting}
          <div class="w-5 h-5 border-2 border-white/50 border-t-transparent rounded-full animate-spin"></div>
          Starting…
        {:else}
          Start workout
        {/if}
      </button>
    </div>
  </div>
{/if}
