<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import SwapSheet from '$lib/components/sessions/SwapSheet.svelte';
  import { muscleLabel } from '$lib/muscle-heat';
  import { readinessColor } from '$lib/readiness';
  import type { SwapAlternative } from '$lib/swap';
  import type {
    AdjustResponse,
    RecommendedExercise,
    SessionDetail,
    TodayRecommendationResponse,
  } from '$lib/types';
  import { formatWeight } from '$lib/utils/format';

  // Today's workout (#13/#14, ADR-0004): drawn from the active Program's next due
  // day, AUTOREGULATED on today's biometric Readiness + per-muscle Recovery (the
  // reason is shown), or freestyle when no Program is active. A conversational
  // "adjust" re-shapes it ("make it shorter / no barbell / I'm tired"). Starting it
  // instantiates a Session pre-filled with the target Sets the user overwrites —
  // their edits always win. Mobile-first.
  let today = $state<TodayRecommendationResponse | null>(null);
  let loading = $state(true);
  let error = $state('');
  let starting = $state(false);

  // Conversational adjust state.
  let adjustOpen = $state(false);
  let adjustText = $state('');
  let adjusting = $state(false);
  let adjustNote = $state('');

  $effect(() => {
    load();
  });

  async function load() {
    loading = true;
    error = '';
    adjustNote = '';
    try {
      today = await api.get<TodayRecommendationResponse>('/api/recommendations/today');
    } catch (err) {
      error = err instanceof Error ? err.message : "Failed to load today's workout";
    } finally {
      loading = false;
    }
  }

  async function applyAdjust() {
    const request = adjustText.trim();
    if (!request || adjusting) return;
    adjusting = true;
    error = '';
    try {
      const res = await api.post<AdjustResponse>('/api/recommendations/adjust', { request });
      today = res;
      adjustNote = res.note;
      adjustText = '';
      adjustOpen = false;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to adjust the workout';
    } finally {
      adjusting = false;
    }
  }

  async function start() {
    if (starting) return;
    starting = true;
    error = '';
    try {
      let created: SessionDetail;
      if (swapped) {
        // A Swapped slot diverges from what a regenerate would produce, so
        // start EXACTLY what's displayed (the WYSIWYG path).
        created = await api.post<SessionDetail>('/api/recommendations/start', {
          exercises: exercises.map((ex) => ({
            exercise_id: ex.exercise_id,
            target_sets: ex.target_sets,
            target_reps: ex.target_reps,
            target_weight_kg: ex.target_weight_kg,
          })),
        });
      } else {
        // If the user adjusted, start the adjusted shape; otherwise today's.
        const path = adjustNote
          ? '/api/recommendations/adjust/start'
          : '/api/recommendations/today/start';
        const body = adjustNote ? { request: lastRequest } : {};
        created = await api.post<SessionDetail>(path, body);
      }
      await goto(`/sessions/${created.id}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to start workout';
      starting = false;
    }
  }

  // --- Swap a slot before starting (CONTEXT.md "Swap") ---
  let swapForId = $state<string | null>(null);
  let swapped = $state(false);
  let altsByExercise = $state<Record<string, SwapAlternative[]>>({});
  const altsRequested = new Set<string>();

  // Prefetch each slot's alternatives once the proposal is loaded, so the
  // sheet opens instantly at the rack.
  $effect(() => {
    for (const ex of exercises) {
      if (altsRequested.has(ex.exercise_id)) continue;
      altsRequested.add(ex.exercise_id);
      void prefetchAlternatives(ex.exercise_id);
    }
  });

  async function prefetchAlternatives(exerciseId: string) {
    try {
      const others = exercises
        .map((e) => e.exercise_id)
        .filter((id) => id !== exerciseId)
        .join(',');
      altsByExercise[exerciseId] = await api.get<SwapAlternative[]>(
        `/api/exercises/${exerciseId}/alternatives${others ? `?exclude=${others}` : ''}`,
      );
    } catch {
      altsRequested.delete(exerciseId); // retry when the sheet opens
    }
  }

  function applySwap(alt: SwapAlternative) {
    if (!today || !swapForId) return;
    const outgoingId = swapForId;
    swapForId = null;
    const replaced: RecommendedExercise[] = exercises.map((ex) =>
      ex.exercise_id === outgoingId
        ? {
            exercise_id: alt.exercise_id,
            name: alt.name,
            // The slot's set COUNT is the muscle's volume — it stays; the
            // prescription is the alternative's OWN Progression.
            target_sets: ex.target_sets,
            target_reps: alt.target_reps,
            target_weight_kg: alt.target_weight_kg,
            is_starting_point: alt.is_starting_point,
            primary_muscles: alt.primary_muscles,
            secondary_muscles: alt.secondary_muscles,
          }
        : ex,
    );
    today = { ...today, exercises: replaced };
    swapped = true;
  }

  async function applyExclude() {
    if (!swapForId) return;
    const id = swapForId;
    swapForId = null;
    try {
      await api.put(`/api/exercises/${id}/exclusion`);
      // The engine now avoids it — regenerate today so the slot refills honestly.
      swapped = false;
      await load();
    } catch {
      error = "Couldn't save the exclusion — check your connection and retry.";
    }
  }

  function swapTargetName(): string {
    return exercises.find((e) => e.exercise_id === swapForId)?.name ?? '';
  }

  // Remember the last applied request so "Start" re-applies it server-side
  // (deterministic with the deterministic provider; the LLM provider re-proposes).
  let lastRequest = $state('');

  const quickAdjusts = ['Make it shorter', "I'm tired", 'No barbell today'];

  async function quickAdjust(text: string) {
    adjustText = text;
    lastRequest = text;
    await applyAdjust();
  }

  // One-tap duration shaper (plan ③): "I have N minutes" → the deterministic
  // shaper fits the day via the bounded adjust levers. The shaped result is
  // exactly what's displayed, so Start switches to the WYSIWYG path.
  const durations = [30, 45, 60];
  let shaping = $state(false);

  async function shapeTo(minutes: number) {
    if (shaping) return;
    shaping = true;
    error = '';
    try {
      const res = await api.post<AdjustResponse>('/api/recommendations/shape', { minutes });
      today = res;
      adjustNote = res.note;
      swapped = true; // start exactly what's displayed
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to shape the workout';
    } finally {
      shaping = false;
    }
  }

  let exercises = $derived(today?.exercises ?? []);
  let isEmpty = $derived(!loading && exercises.length === 0);
  let ctx = $derived(today?.program ?? null);
  let auto = $derived(ctx?.autoregulation ?? null);

  // The band a numeric readiness falls in, for the reason-banner colour.
  function bandFor(r: number): 'low' | 'moderate' | 'high' {
    return r >= 65 ? 'high' : r < 40 ? 'low' : 'moderate';
  }
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

  {#if auto?.early_deload}
    <div class="px-4 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30">
      <p class="text-xs font-medium text-amber-300">
        Fatigue building — your recent readiness has been low, so we've pulled a
        deload forward. Lighter is the right call.
      </p>
    </div>
  {/if}

  <!-- Autoregulation reason (#14): why today's volume looks the way it does. -->
  {#if auto && (auto.adjusted || auto.reason)}
    <div class="flex items-start gap-2.5 px-4 py-3 rounded-xl bg-surface-800 border border-surface-700">
      {#if auto.readiness !== null}
        <span class="shrink-0 mt-0.5 text-sm font-bold tabular-nums {readinessColor(bandFor(auto.readiness))}">
          {Math.round(auto.readiness)}
        </span>
      {/if}
      <p class="text-xs text-surface-300 leading-relaxed">{auto.reason}</p>
    </div>
  {/if}

  {#if adjustNote}
    <div class="px-4 py-2.5 rounded-xl bg-primary-500/10 border border-primary-500/30">
      <p class="text-xs font-medium text-primary-200">Adjusted: {adjustNote}</p>
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
            <div class="shrink-0 flex items-start gap-2.5">
              <div class="text-right">
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
              <button
                onclick={() => (swapForId = ex.exercise_id)}
                class="p-1.5 -mr-1 rounded-lg text-surface-500 hover:text-surface-200 hover:bg-surface-700 transition-colors"
                aria-label="Swap {ex.name}"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" /></svg>
              </button>
            </div>
          </div>
        </li>
      {/each}
    </ul>

    {#if ctx}
      <a
        href="/programs/{ctx.program_id}"
        class="block text-center text-xs text-primary-400 hover:text-primary-300 underline underline-offset-2"
      >
        Why these numbers? See the science behind your plan →
      </a>
    {/if}

    <p class="text-center text-xs text-surface-600">
      You can change any weight, reps, or set once you start — your edits always win.
    </p>

    <!-- Conversational adjust (#14) -->
    <div class="rounded-xl bg-surface-800/60 border border-surface-700/60 p-3 space-y-2">
      <div class="flex items-center justify-between">
        <p class="text-xs font-semibold text-surface-300">Adjust today</p>
        <button
          onclick={() => (adjustOpen = !adjustOpen)}
          class="text-[11px] text-primary-400 hover:text-primary-300"
        >
          {adjustOpen ? 'Close' : 'Tweak it'}
        </button>
      </div>
      <div class="flex items-center gap-1.5">
        <span class="text-[11px] text-surface-500 shrink-0">Time I have:</span>
        {#each durations as m (m)}
          <button
            onclick={() => shapeTo(m)}
            disabled={shaping}
            class="px-2.5 py-1 rounded-full text-[11px] bg-surface-700 hover:bg-surface-600 text-surface-200 transition-colors disabled:opacity-50 tabular-nums"
          >
            {m} min
          </button>
        {/each}
      </div>
      <div class="flex flex-wrap gap-1.5">
        {#each quickAdjusts as q (q)}
          <button
            onclick={() => quickAdjust(q)}
            disabled={adjusting}
            class="px-2.5 py-1 rounded-full text-[11px] bg-surface-700 hover:bg-surface-600 text-surface-200 transition-colors disabled:opacity-50"
          >
            {q}
          </button>
        {/each}
      </div>
      {#if adjustOpen}
        <div class="flex gap-2">
          <input
            bind:value={adjustText}
            onkeydown={(e) => { if (e.key === 'Enter') { lastRequest = adjustText.trim(); applyAdjust(); } }}
            placeholder="e.g. dumbbells only, keep it under 30 min"
            class="flex-1 px-3 py-2 rounded-lg bg-surface-900 border border-surface-700 text-sm text-surface-100 placeholder:text-surface-600 focus:outline-none focus:border-primary-500"
          />
          <button
            onclick={() => { lastRequest = adjustText.trim(); applyAdjust(); }}
            disabled={adjusting || !adjustText.trim()}
            class="shrink-0 px-3 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium transition-colors disabled:opacity-50"
          >
            {adjusting ? '…' : 'Apply'}
          </button>
        </div>
      {/if}
    </div>
  {/if}
</div>

<SwapSheet
  open={swapForId !== null}
  exerciseName={swapTargetName()}
  alternatives={swapForId ? (altsByExercise[swapForId] ?? null) : null}
  onpick={applySwap}
  onexclude={applyExclude}
  onclose={() => (swapForId = null)}
/>

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
