<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import { muscleLabel } from '$lib/muscle-heat';
  import type { RecommendationResponse, SessionDetail } from '$lib/types';
  import { formatWeight } from '$lib/utils/format';

  // "Generate me a workout" — the freestyle Recommendation flow (#11). We preview
  // a deterministic proposal (Exercises × target sets/reps/weight, biased toward
  // fresh muscles within the user's Gym Profile), the user reviews it, then
  // "Start workout" instantiates a Session pre-filled with those Sets and drops
  // them straight into the live logging UI. Mobile-first; no LLM (deterministic
  // core, ADR-0002).
  let recommendation = $state<RecommendationResponse | null>(null);
  let loading = $state(true);
  let error = $state('');
  let starting = $state(false);
  // Guards against overlapping generate requests (rapid Regenerate/Try-again taps).
  let inFlight = false;

  $effect(() => {
    load();
  });

  async function load() {
    if (inFlight) return;
    inFlight = true;
    loading = true;
    error = '';
    try {
      recommendation = await api.get<RecommendationResponse>(
        '/api/recommendations/freestyle',
      );
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to generate a workout';
    } finally {
      loading = false;
      inFlight = false;
    }
  }

  async function startWorkout() {
    if (starting) return;
    starting = true;
    error = '';
    try {
      // The engine regenerates deterministically server-side, so the started
      // Session matches the proposal just reviewed.
      const created = await api.post<SessionDetail>(
        '/api/recommendations/freestyle/start',
        {},
      );
      await goto(`/sessions/${created.id}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to start workout';
      starting = false;
    }
  }

  let exercises = $derived(recommendation?.exercises ?? []);
  let isEmpty = $derived(!loading && exercises.length === 0);
</script>

<div class="space-y-4 pb-28">
  <div class="flex items-center gap-3">
    <a
      href="/sessions"
      class="shrink-0 p-2 -ml-2 rounded-lg text-surface-400 hover:text-surface-200 hover:bg-surface-800 transition-colors"
      aria-label="Back to Train"
    >
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
      </svg>
    </a>
    <div>
      <h1 class="text-2xl font-semibold text-surface-100">Generated workout</h1>
      <p class="text-xs text-surface-500">
        Built from your recent training, recovery, and gym equipment.
      </p>
    </div>
  </div>

  {#if error}
    <div class="p-4 rounded-xl bg-red-500/10 border border-red-500/30">
      <p class="text-sm text-red-400">{error}</p>
      <button
        onclick={load}
        class="mt-2 text-xs font-medium text-red-300 underline underline-offset-2"
      >
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
      <svg class="w-12 h-12 text-surface-600 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
      </svg>
      <p class="text-surface-300 text-sm font-medium">Not enough history yet</p>
      <p class="mt-1 text-surface-500 text-xs max-w-xs mx-auto">
        Log a few Sessions first — the generator builds your next workout from the
        Exercises you've trained and the equipment in your Gym Profile.
      </p>
      <a
        href="/sessions"
        class="inline-block mt-4 px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold transition-colors"
      >
        Start logging
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

<!-- Sticky start bar: the primary action stays in the thumb zone. -->
{#if !loading && !isEmpty}
  <div class="fixed inset-x-0 bottom-16 sm:bottom-0 px-4 pb-3 pt-2 bg-gradient-to-t from-surface-900 via-surface-900/95 to-transparent">
    <div class="max-w-2xl mx-auto flex gap-2">
      <button
        onclick={load}
        disabled={starting || loading}
        class="shrink-0 px-4 py-3.5 rounded-2xl border border-surface-700 text-surface-300 hover:bg-surface-800 text-sm font-medium transition-colors disabled:opacity-50"
        aria-label="Regenerate"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
        </svg>
      </button>
      <button
        onclick={startWorkout}
        disabled={starting}
        class="flex-1 flex items-center justify-center gap-2 py-3.5 rounded-2xl bg-primary-500 hover:bg-primary-600 text-white font-semibold text-base transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-primary-500/20"
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
