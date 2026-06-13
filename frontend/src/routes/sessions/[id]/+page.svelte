<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { api, ApiError } from '$lib/api';
  import EffortChips from '$lib/components/sessions/EffortChips.svelte';
  import ExercisePicker from '$lib/components/sessions/ExercisePicker.svelte';
  import PRCelebration from '$lib/components/sessions/PRCelebration.svelte';
  import SetTypeChip from '$lib/components/sessions/SetTypeChip.svelte';
  import {
    celebratablePrs,
    detectPrs,
    priorBestsFromSets,
    type PRResult,
  } from '$lib/pr';
  import type {
    ExerciseSummary,
    PRReadout,
    SessionDetail,
    SetCreate,
    SetType,
    SetUpdate,
    SetWriteResult,
    TrainingSet,
  } from '$lib/types';
  import { formatNumber } from '$lib/utils/format';

  // The live gym-logging surface. A Session is an ordered list of Sets; we render
  // them grouped by Exercise (consecutive same-exercise sets share a header,
  // Fitbod/Hevy style) while order is the flat server-side order_index. Mobile-
  // first: big steppers, one-tap set-type and Effort chips, reorder by arrows.
  let sessionId = $derived($page.params.id);
  let session = $state<SessionDetail | null>(null);
  let loading = $state(true);
  let error = $state('');
  let notFound = $state(false);
  let pickerOpen = $state(false);
  let finishing = $state(false);
  // The PRs currently being celebrated (CONTEXT.md "PR"). Client-side detection
  // fills this instantly when a Set is logged — offline included — then the
  // server's authoritative result reconciles it on the response.
  let celebratedPrs = $state<PRResult[]>([]);

  $effect(() => {
    const _id = sessionId;
    load();
  });

  // --- PR detection (client-side first, server-authoritative on sync). ---

  /**
   * Detect PRs for a candidate Set against the user's history KNOWN TO THE
   * CLIENT — the other Sets of the same Exercise already in this Session. This
   * runs with no network so a PR celebrates instantly while offline. It is a
   * conservative subset: PRs spanning earlier Sessions are caught by the server
   * and arrive via {@link reconcileServerPrs}.
   */
  function detectClientSide(
    exerciseId: string,
    weightKg: number,
    reps: number,
    setType: SetType,
    rir: number | null,
    excludeSetId?: string,
  ): PRResult[] {
    const history = (session?.sets ?? [])
      .filter(
        (s) =>
          s.exercise_id === exerciseId &&
          s.set_type === 'normal' &&
          s.id !== excludeSetId,
      )
      .map((s) => ({ weightKg: s.weight_kg, reps: s.reps, rir: s.effort_rir }));
    return detectPrs({
      weightKg,
      reps,
      setType,
      rir,
      prior: priorBestsFromSets(history),
    });
  }

  /** Map the server's authoritative PR readouts to the celebration shape. */
  function reconcileServerPrs(prs: PRReadout[]): PRResult[] {
    return prs.map((p) => ({
      kind: p.kind,
      value: p.value,
      atWeightKg: p.at_weight_kg,
    }));
  }

  function celebrate(prs: PRResult[]) {
    // Replace (don't append) so the banner always reflects the latest write.
    // De-noise: a weight PR already implies the trivial first-rep-at-that-weight,
    // so don't double up the banner (the dimension is still persisted server-side).
    celebratedPrs = celebratablePrs(prs);
  }

  async function load() {
    loading = true;
    error = '';
    notFound = false;
    try {
      session = await api.get<SessionDetail>(`/api/sessions/${sessionId}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) notFound = true;
      else error = err instanceof Error ? err.message : 'Failed to load session';
    } finally {
      loading = false;
    }
  }

  // --- Grouping: consecutive same-exercise sets share one header. ---
  interface Group {
    exerciseId: string;
    exerciseName: string;
    sets: TrainingSet[];
  }
  let groups = $derived.by<Group[]>(() => {
    if (!session) return [];
    const out: Group[] = [];
    for (const s of session.sets) {
      const last = out[out.length - 1];
      if (last && last.exerciseId === s.exercise_id) {
        last.sets.push(s);
      } else {
        out.push({
          exerciseId: s.exercise_id,
          exerciseName: s.exercise_name ?? 'Exercise',
          sets: [s],
        });
      }
    }
    return out;
  });

  // The last set of each exercise group gets the Effort nudge (CONTEXT.md).
  let lastSetIdOfGroup = $derived(
    new Set(groups.map((g) => g.sets[g.sets.length - 1].id)),
  );

  // --- Mutations (reload-after-write keeps order_index + volume correct). ---

  async function addExercise(ex: ExerciseSummary) {
    pickerOpen = false;
    await addSet({ exercise_id: ex.id, weight_kg: 0, reps: 8 });
  }

  // "Add set" within a group copies the group's last set (weight/reps/type) —
  // the common case is another set of the same thing.
  async function addAnotherSet(group: Group) {
    const prev = group.sets[group.sets.length - 1];
    await addSet({
      exercise_id: group.exerciseId,
      weight_kg: prev.weight_kg,
      reps: prev.reps,
      set_type: prev.set_type,
    });
  }

  async function addSet(payload: SetCreate) {
    if (!session) return;
    // Detect PRs client-side FIRST (instant, offline-capable) against the sets
    // already known. Celebrate immediately; the server reconciles below.
    const clientPrs = detectClientSide(
      payload.exercise_id,
      payload.weight_kg,
      payload.reps,
      payload.set_type ?? 'normal',
      payload.effort_rir ?? null,
    );
    if (clientPrs.length > 0) celebrate(clientPrs);
    try {
      const result = await api.post<SetWriteResult>(
        `/api/sessions/${session.id}/sets`,
        payload,
      );
      // Server is authoritative (full history, no false PRs): use its verdict.
      celebrate(reconcileServerPrs(result.prs));
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to add set';
    }
  }

  // Debounced patch so holding the stepper doesn't flood the API. Keyed per set.
  const patchTimers = new Map<string, ReturnType<typeof setTimeout>>();
  function patchSetDebounced(setId: string, body: SetUpdate) {
    if (!session) return;
    // Apply locally first for instant feedback.
    const s = session.sets.find((x) => x.id === setId);
    if (s) {
      if (body.weight_kg !== undefined) s.weight_kg = body.weight_kg;
      if (body.reps !== undefined) s.reps = body.reps;
    }
    const existing = patchTimers.get(setId);
    if (existing) clearTimeout(existing);
    patchTimers.set(
      setId,
      setTimeout(async () => {
        try {
          const result = await api.patch<SetWriteResult>(
            `/api/sessions/${session!.id}/sets/${setId}`,
            body,
          );
          // Editing weight/reps up can mint a PR — celebrate the server verdict.
          celebrate(reconcileServerPrs(result.prs));
          await load();
        } catch (err) {
          error = err instanceof Error ? err.message : 'Failed to update set';
        }
      }, 500),
    );
  }

  // Set-type and Effort apply immediately (single taps, not held).
  async function patchSetNow(setId: string, body: SetUpdate) {
    if (!session) return;
    try {
      const result = await api.patch<SetWriteResult>(
        `/api/sessions/${session.id}/sets/${setId}`,
        body,
      );
      // e.g. flipping a warmup → normal can reveal a PR; celebrate the verdict.
      celebrate(reconcileServerPrs(result.prs));
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to update set';
    }
  }

  function stepWeight(s: TrainingSet, delta: number) {
    const next = Math.max(0, Math.round((s.weight_kg + delta) * 100) / 100);
    patchSetDebounced(s.id, { weight_kg: next });
  }
  function stepReps(s: TrainingSet, delta: number) {
    const next = Math.max(0, s.reps + delta);
    patchSetDebounced(s.id, { reps: next });
  }
  function onWeightInput(s: TrainingSet, e: Event) {
    const v = parseFloat((e.target as HTMLInputElement).value);
    if (!Number.isNaN(v)) patchSetDebounced(s.id, { weight_kg: Math.max(0, v) });
  }
  function onRepsInput(s: TrainingSet, e: Event) {
    const v = parseInt((e.target as HTMLInputElement).value, 10);
    if (!Number.isNaN(v)) patchSetDebounced(s.id, { reps: Math.max(0, v) });
  }

  async function deleteSet(setId: string) {
    if (!session) return;
    try {
      await api.delete(`/api/sessions/${session.id}/sets/${setId}`);
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to delete set';
    }
  }

  // Reorder: move a set one slot up/down in the flat order, then PUT the new id
  // order. Disabled at the ends.
  async function moveSet(index: number, dir: -1 | 1) {
    if (!session) return;
    const ids = session.sets.map((s) => s.id);
    const target = index + dir;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    try {
      session = await api.put<SessionDetail>(
        `/api/sessions/${session.id}/sets/order`,
        { set_ids: ids },
      );
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to reorder';
      await load();
    }
  }

  async function finish() {
    if (!session || finishing) return;
    finishing = true;
    try {
      await api.post(`/api/sessions/${session.id}/finish`);
      await goto('/sessions');
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to finish session';
      finishing = false;
    }
  }

  async function deleteSession() {
    if (!session) return;
    if (!confirm('Delete this entire session and all its sets?')) return;
    try {
      await api.delete(`/api/sessions/${session.id}`);
      await goto('/sessions');
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to delete session';
    }
  }

  // Flat index of a set within the whole session (for reorder arrows).
  function flatIndex(setId: string): number {
    return session ? session.sets.findIndex((s) => s.id === setId) : -1;
  }
</script>

<div class="space-y-4 pb-28">
  <a href="/sessions" class="inline-flex items-center gap-1.5 text-sm text-surface-400 hover:text-surface-200 transition-colors">
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
    </svg>
    Sessions
  </a>

  {#if loading}
    <div class="space-y-3 animate-pulse">
      <div class="w-1/2 h-7 bg-surface-700 rounded"></div>
      <div class="h-32 bg-surface-800 rounded-xl"></div>
      <div class="h-32 bg-surface-800 rounded-xl"></div>
    </div>
  {:else if notFound}
    <div class="p-12 text-center bg-surface-800 rounded-xl border border-surface-700">
      <p class="text-surface-300 font-medium">Session not found</p>
      <p class="text-surface-500 text-sm mt-1">It may belong to another user or no longer exist.</p>
    </div>
  {:else if error && !session}
    <div class="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400">{error}</p>
      <button class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm" onclick={load}>Retry</button>
    </div>
  {:else if session}
    <!-- Header -->
    <div class="flex items-start justify-between gap-3">
      <div>
        <h1 class="text-2xl font-semibold text-surface-100 flex items-center gap-2">
          Session
          {#if session.is_active}
            <span class="text-[0.6rem] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full bg-primary-500/20 text-primary-300">Active</span>
          {/if}
        </h1>
        <p class="mt-0.5 text-xs text-surface-500">
          {session.set_count} set{session.set_count !== 1 ? 's' : ''}
          {#if session.total_volume_kg > 0}
            · {formatNumber(session.total_volume_kg)} kg volume
          {/if}
        </p>
      </div>
      <button onclick={deleteSession} class="p-2 text-surface-500 hover:text-red-400 transition-colors" aria-label="Delete session">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
        </svg>
      </button>
    </div>

    {#if error}
      <p class="text-sm text-red-400">{error}</p>
    {/if}

    <!-- Exercise groups -->
    {#each groups as group (group.exerciseId + '-' + group.sets[0].id)}
      <div class="bg-surface-800 rounded-2xl border border-surface-700 overflow-hidden">
        <div class="flex items-center justify-between px-4 py-3 border-b border-surface-700/70">
          <a href="/exercises/{group.exerciseId}" class="text-sm font-semibold text-surface-100 hover:text-primary-300 transition-colors truncate">
            {group.exerciseName}
          </a>
          <span class="text-xs text-surface-500 shrink-0">{group.sets.length} set{group.sets.length !== 1 ? 's' : ''}</span>
        </div>

        <div class="divide-y divide-surface-700/50">
          {#each group.sets as s, i (s.id)}
            {@const fi = flatIndex(s.id)}
            <div class="p-3 space-y-2.5">
              <div class="flex items-center gap-2">
                <!-- Set number within the group -->
                <span class="shrink-0 w-6 h-6 rounded-full bg-surface-700 text-surface-300 text-xs flex items-center justify-center font-semibold">
                  {i + 1}
                </span>

                <SetTypeChip value={s.set_type} onchange={(v: SetType) => patchSetNow(s.id, { set_type: v })} />

                <!-- Weight stepper -->
                <div class="flex items-center gap-1 flex-1">
                  <button onclick={() => stepWeight(s, -2.5)} class="w-8 h-8 rounded-lg bg-surface-700 text-surface-200 text-lg font-medium hover:bg-surface-600 active:bg-surface-500 transition-colors" aria-label="Decrease weight">−</button>
                  <div class="relative flex-1 min-w-0">
                    <input
                      type="number"
                      inputmode="decimal"
                      step="0.5"
                      value={s.weight_kg}
                      oninput={(e) => onWeightInput(s, e)}
                      class="w-full text-center py-1.5 bg-surface-900 border border-surface-700 rounded-lg text-surface-100 text-sm font-semibold focus:outline-none focus:border-primary-500"
                      aria-label="Weight in kg"
                    />
                    <span class="absolute right-1.5 top-1/2 -translate-y-1/2 text-[0.6rem] text-surface-500 pointer-events-none">kg</span>
                  </div>
                  <button onclick={() => stepWeight(s, 2.5)} class="w-8 h-8 rounded-lg bg-surface-700 text-surface-200 text-lg font-medium hover:bg-surface-600 active:bg-surface-500 transition-colors" aria-label="Increase weight">+</button>
                </div>

                <span class="text-surface-600 text-sm">×</span>

                <!-- Reps stepper -->
                <div class="flex items-center gap-1">
                  <button onclick={() => stepReps(s, -1)} class="w-8 h-8 rounded-lg bg-surface-700 text-surface-200 text-lg font-medium hover:bg-surface-600 active:bg-surface-500 transition-colors" aria-label="Decrease reps">−</button>
                  <input
                    type="number"
                    inputmode="numeric"
                    value={s.reps}
                    oninput={(e) => onRepsInput(s, e)}
                    class="w-12 text-center py-1.5 bg-surface-900 border border-surface-700 rounded-lg text-surface-100 text-sm font-semibold focus:outline-none focus:border-primary-500"
                    aria-label="Reps"
                  />
                  <button onclick={() => stepReps(s, 1)} class="w-8 h-8 rounded-lg bg-surface-700 text-surface-200 text-lg font-medium hover:bg-surface-600 active:bg-surface-500 transition-colors" aria-label="Increase reps">+</button>
                </div>
              </div>

              <!-- Effort + reorder/delete row -->
              <div class="flex items-center justify-between gap-2 pl-8">
                <EffortChips
                  value={s.effort_rir}
                  nudge={lastSetIdOfGroup.has(s.id)}
                  onchange={(v: number | null) => patchSetNow(s.id, { effort_rir: v })}
                />
                <div class="flex items-center gap-0.5">
                  <button onclick={() => moveSet(fi, -1)} disabled={fi <= 0} class="w-7 h-7 rounded-md text-surface-500 hover:text-surface-200 hover:bg-surface-700 disabled:opacity-20 disabled:hover:bg-transparent transition-colors" aria-label="Move set up">
                    <svg class="w-4 h-4 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 15.75l7.5-7.5 7.5 7.5" /></svg>
                  </button>
                  <button onclick={() => moveSet(fi, 1)} disabled={fi >= (session?.sets.length ?? 0) - 1} class="w-7 h-7 rounded-md text-surface-500 hover:text-surface-200 hover:bg-surface-700 disabled:opacity-20 disabled:hover:bg-transparent transition-colors" aria-label="Move set down">
                    <svg class="w-4 h-4 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" /></svg>
                  </button>
                  <button onclick={() => deleteSet(s.id)} class="w-7 h-7 rounded-md text-surface-500 hover:text-red-400 hover:bg-red-500/10 transition-colors" aria-label="Delete set">
                    <svg class="w-4 h-4 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.75"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
                  </button>
                </div>
              </div>
            </div>
          {/each}
        </div>

        <button
          onclick={() => addAnotherSet(group)}
          class="w-full py-2.5 text-sm font-medium text-primary-300 hover:bg-primary-500/10 transition-colors border-t border-surface-700/70"
        >
          + Add set
        </button>
      </div>
    {/each}

    <!-- Add exercise -->
    <button
      onclick={() => (pickerOpen = true)}
      class="w-full py-3.5 rounded-2xl border-2 border-dashed border-surface-700 text-surface-300
             hover:border-primary-500/50 hover:text-primary-300 font-medium text-sm transition-colors
             flex items-center justify-center gap-2"
    >
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" /></svg>
      Add exercise
    </button>

    {#if groups.length === 0}
      <p class="text-center text-sm text-surface-500 pt-2">Add your first exercise to start logging sets.</p>
    {/if}
  {/if}
</div>

<!-- Finish bar (active sessions only), above the bottom nav -->
{#if session?.is_active}
  <div class="fixed bottom-[calc(3.5rem+env(safe-area-inset-bottom))] lg:bottom-0 inset-x-0 z-20 p-3 bg-gradient-to-t from-surface-950 via-surface-950/95 to-transparent">
    <div class="max-w-3xl mx-auto lg:pl-64">
      <button
        onclick={finish}
        disabled={finishing}
        class="w-full py-3 rounded-xl bg-primary-500 hover:bg-primary-600 text-white font-semibold text-sm
               transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-lg"
      >
        {finishing ? 'Finishing…' : 'Finish session'}
      </button>
    </div>
  </div>
{/if}

<ExercisePicker open={pickerOpen} onpick={addExercise} onclose={() => (pickerOpen = false)} />

<PRCelebration prs={celebratedPrs} onclose={() => (celebratedPrs = [])} />
