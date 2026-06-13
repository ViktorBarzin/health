<script lang="ts">
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import EffortChips from '$lib/components/sessions/EffortChips.svelte';
  import ExercisePicker from '$lib/components/sessions/ExercisePicker.svelte';
  import PlateCalculator from '$lib/components/sessions/PlateCalculator.svelte';
  import PRCelebration from '$lib/components/sessions/PRCelebration.svelte';
  import RestTimer from '$lib/components/sessions/RestTimer.svelte';
  import SetTypeChip from '$lib/components/sessions/SetTypeChip.svelte';
  import SyncIndicator from '$lib/components/sessions/SyncIndicator.svelte';
  import type { GymEquipment } from '$lib/plates';
  import {
    celebratablePrs,
    detectPrs,
    priorBestsFromSets,
    type PRResult,
  } from '$lib/pr';
  import { createSessionStore } from '$lib/sync/session-store.svelte';
  import { getKV, putKV } from '$lib/sync/store';
  import { nextGroupId, groupSessionSets, nextSupersetExerciseId } from '$lib/superset';
  import type {
    ExerciseSummary,
    GymProfile,
    RestPref,
    SetCreate,
    SetType,
    SetUpdate,
    TrainingSet,
  } from '$lib/types';
  import { requestWakeLock, type WakeLockHandle } from '$lib/wake-lock';
  import { formatNumber } from '$lib/utils/format';

  // The live gym-logging surface — OFFLINE-FIRST (ADR-0005, #6). A Session is an
  // ordered list of Sets; we render them in blocks (lib/superset.ts) —
  // consecutive same-exercise sets share a header (Fitbod/Hevy style), and Sets
  // in a Superset render as one alternation block. Mobile-first: big steppers,
  // one-tap chips, a rest timer that auto-starts on each logged Set, a
  // plate/warm-up calculator per row, and a screen wake-lock.
  //
  // Every mutation goes through an offline-capable data layer (createSessionStore):
  // it updates the optimistic snapshot immediately and enqueues a durable op
  // (IndexedDB) that syncs to /api/sessions when connectivity returns. The UI
  // never waits on the network, so logging works in a gym dead zone and survives
  // a kill/reload mid-Session.
  let sessionId = $derived($page.params.id ?? '');
  let store = $derived(createSessionStore(sessionId));
  // The optimistic Session snapshot the whole template binds to (was `session`).
  let session = $derived(store.snapshot);
  let loading = $derived(store.loading);
  let notFound = $derived(store.notFound);
  let error = $state('');
  let pickerOpen = $state(false);
  let finishing = $state(false);
  let celebratedPrs = $state<PRResult[]>([]);

  // --- In-gym toolkit state (#7) ---

  // Per-exercise effective rest durations (seconds), fetched lazily and cached.
  let restByExercise = $state<Record<string, number>>({});
  // Rest-timer trigger: a counter the RestTimer watches; bumping it (re)starts it.
  let restSignal = $state(0);
  let restDuration = $state(120);

  // The user's Gym Profile (bar + plates), for the plate/warm-up calculator.
  let gymProfile = $state<GymProfile | null>(null);
  let calcOpen = $state(false);
  let calcWeight = $state(0);
  let calcReps = $state(8);

  // Superset build mode: tapping sets selects them; confirming groups them.
  let supersetMode = $state(false);
  let selectedSetIds = $state<Set<string>>(new Set());

  // Screen wake-lock: held while the Session is active.
  let wakeLock: WakeLockHandle | null = null;

  // The calculator loads against the user's heaviest bar (their standard
  // barbell): bar_weights_kg is stored sorted ascending, so [0] would be the
  // LIGHTEST (e.g. a 15 kg technique bar) — pick the max instead.
  let plateEquipment = $derived<GymEquipment | null>(
    gymProfile && gymProfile.bar_weights_kg.length > 0
      ? {
          bar: Math.max(...gymProfile.bar_weights_kg),
          plates: gymProfile.plate_weights_kg,
        }
      : null,
  );

  // Load through the offline store, then prefetch the day's context so logging
  // works with zero signal. Re-runs when the session id changes; tears the old
  // store's drain-listener down.
  $effect(() => {
    const s = store;
    s.load().then(() => {
      void prefetchRest();
      void prefetchContext();
    });
    return () => s.destroy();
  });

  // Hold a wake-lock while the Session is active. Depend on a $derived BOOLEAN
  // so the effect re-runs only when active-ness actually flips.
  let sessionActive = $derived(session?.is_active ?? false);
  $effect(() => {
    if (!sessionActive) return;
    const handle = requestWakeLock();
    wakeLock = handle;
    return () => {
      handle.release();
      if (wakeLock === handle) wakeLock = null;
    };
  });

  // --- Prefetch the day's context (ADR-0005): cache what the logging screen
  // needs so it works offline — the Gym Profile (plate math) and per-exercise
  // rest. Cached in IndexedDB KV so a reload while offline still has them. ---

  async function prefetchContext() {
    // Gym Profile: try the network, fall back to the cached copy.
    try {
      const p = await api.get<GymProfile>('/api/gym-profile');
      gymProfile = p;
      await putKV('gym-profile', p);
    } catch {
      gymProfile = (await getKV<GymProfile>('gym-profile')) ?? null;
    }
  }

  // --- PR detection (client-side, fires offline — ADR-0005). The server is the
  // record-of-truth and reconciles authoritative PRs on sync (surfaced via the
  // /prs endpoint / history), so the live banner is the instant client signal. ---

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

  function celebrate(prs: PRResult[]) {
    celebratedPrs = celebratablePrs(prs);
  }

  // Fetch the effective rest duration for any exercise in the Session we haven't
  // cached yet (so the timer can start with the right value the moment a set
  // lands). Best-effort + IndexedDB-cached so it survives offline reloads.
  async function prefetchRest() {
    const ids = [...new Set((session?.sets ?? []).map((s) => s.exercise_id))];
    await Promise.all(
      ids
        .filter((id) => !(id in restByExercise))
        .map(async (id) => {
          try {
            const pref = await api.get<RestPref>(`/api/exercises/${id}/rest`);
            restByExercise[id] = pref.effective_rest_seconds;
            await putKV(`rest:${id}`, pref.effective_rest_seconds);
          } catch {
            restByExercise[id] =
              (await getKV<number>(`rest:${id}`)) ?? 120;
          }
        }),
    );
  }

  function startRestFor(exerciseId: string) {
    restDuration = restByExercise[exerciseId] ?? 120;
    restSignal += 1; // bump → RestTimer (re)starts
  }

  // --- Blocks: standalone exercise runs + superset alternation groups. ---
  let blocks = $derived(groupSessionSets(session?.sets ?? []));

  function exerciseName(exerciseId: string): string {
    return (
      session?.sets.find((s) => s.exercise_id === exerciseId)?.exercise_name ??
      'Exercise'
    );
  }

  // The Effort nudge lands on the last set of each exercise WITHIN A BLOCK: for a
  // single-exercise block its final set; for a superset, the final set of each
  // distinct exercise in that block. Derived per-block (not per-exercise across
  // the whole session) so an exercise trained in two separate blocks is nudged
  // in each, and a superset nudges every movement it alternates.
  let nudgeSetIds = $derived.by(() => {
    const ids = new Set<string>();
    for (const block of blocks) {
      const lastByExercise: Record<string, string> = {};
      for (const s of block.sets) lastByExercise[s.exercise_id] = s.id;
      for (const id of Object.values(lastByExercise)) ids.add(id);
    }
    return ids;
  });

  // --- Mutations (offline-first: optimistic snapshot + queued op, no reload). ---

  async function addExercise(ex: ExerciseSummary) {
    pickerOpen = false;
    // Remember the picked name so the block header reads right offline (the
    // store can't resolve a name with no signal).
    await addSet({ exercise_id: ex.id, weight_kg: 0, reps: 8 });
    store.setExerciseName(ex.id, ex.name);
  }

  // "Add set" within a block copies the block's last set; for a superset it
  // auto-advances to the NEXT exercise in the rotation (logged in alternation).
  async function addAnotherSet(lastSet: TrainingSet, supersetGroup: number | null) {
    const nextExerciseId =
      supersetGroup !== null
        ? nextSupersetExerciseId(session?.sets ?? [], lastSet.id)
        : null;
    await addSet({
      exercise_id: nextExerciseId ?? lastSet.exercise_id,
      weight_kg: lastSet.weight_kg,
      reps: lastSet.reps,
      set_type: lastSet.set_type,
      superset_group: supersetGroup ?? undefined,
    });
  }

  async function addSet(payload: SetCreate) {
    if (!session) return;
    // PR detection fires instantly client-side (offline included); the server
    // reconciles authoritative records on sync.
    const clientPrs = detectClientSide(
      payload.exercise_id,
      payload.weight_kg,
      payload.reps,
      payload.set_type ?? 'normal',
      payload.effort_rir ?? null,
    );
    if (clientPrs.length > 0) celebrate(clientPrs);
    await store.addSet(payload);
    // Auto-start the rest timer for the exercise just logged.
    await ensureRest(payload.exercise_id);
    startRestFor(payload.exercise_id);
  }

  async function ensureRest(exerciseId: string) {
    if (exerciseId in restByExercise) return;
    try {
      const pref = await api.get<RestPref>(`/api/exercises/${exerciseId}/rest`);
      restByExercise[exerciseId] = pref.effective_rest_seconds;
      await putKV(`rest:${exerciseId}`, pref.effective_rest_seconds);
    } catch {
      restByExercise[exerciseId] = (await getKV<number>(`rest:${exerciseId}`)) ?? 120;
    }
  }

  // Stepper: reflect the new value instantly (previewPatch — no op), debounce
  // the durable write so a drag mints ONE op carrying the final value.
  const patchTimers = new Map<string, ReturnType<typeof setTimeout>>();
  function patchSetDebounced(setId: string, body: SetUpdate) {
    if (!session) return;
    store.previewPatch(setId, body);
    const existing = patchTimers.get(setId);
    if (existing) clearTimeout(existing);
    patchTimers.set(
      setId,
      setTimeout(() => {
        void store.patchSet(setId, body);
      }, 500),
    );
  }

  // Immediate patch (set-type / Effort chips): optimistic + queued at once. May
  // turn a set into a PR (e.g. warmup→normal), so re-detect for the banner.
  async function patchSetNow(setId: string, body: SetUpdate) {
    if (!session) return;
    const s = session.sets.find((x) => x.id === setId);
    if (s) {
      const nextType = body.set_type ?? s.set_type;
      const nextRir = 'effort_rir' in body ? (body.effort_rir ?? null) : s.effort_rir;
      const prs = detectClientSide(
        s.exercise_id,
        body.weight_kg ?? s.weight_kg,
        body.reps ?? s.reps,
        nextType,
        nextRir,
        s.id,
      );
      if (prs.length > 0) celebrate(prs);
    }
    await store.patchSet(setId, body);
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
    await store.deleteSet(setId);
  }

  async function moveSet(index: number, dir: -1 | 1) {
    if (!session) return;
    const ids = session.sets.map((s) => s.id);
    const target = index + dir;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    await store.reorder(ids);
  }

  // --- Plate calculator ---
  function openCalc(s: TrainingSet) {
    calcWeight = s.weight_kg;
    calcReps = s.reps;
    calcOpen = true;
  }

  // --- Rest editor: set a per-exercise default from the UI. The rest PREFERENCE
  // is a settings write (best-effort online); the local + cached value updates
  // regardless so the timer reflects it immediately. ---
  async function editRest(exerciseId: string) {
    const current = restByExercise[exerciseId] ?? 120;
    const input = prompt('Rest seconds for this exercise:', String(current));
    if (input === null) return;
    const secs = parseInt(input, 10);
    if (Number.isNaN(secs) || secs < 5 || secs > 1800) return;
    restByExercise[exerciseId] = secs;
    await putKV(`rest:${exerciseId}`, secs);
    try {
      const pref = await api.put<RestPref>(`/api/exercises/${exerciseId}/rest`, {
        default_rest_seconds: secs,
      });
      restByExercise[exerciseId] = pref.effective_rest_seconds;
      await putKV(`rest:${exerciseId}`, pref.effective_rest_seconds);
    } catch {
      // Offline: the override is applied locally + cached; it will not persist
      // server-side this session, which is acceptable for a rest preference.
    }
  }

  // --- Supersets (offline-capable: expressed as `superset_group` patches that
  // replay through the normal Set-patch endpoint; ADR-0005). ---
  function toggleSupersetMode() {
    supersetMode = !supersetMode;
    selectedSetIds = new Set();
  }
  function toggleSelect(setId: string) {
    const next = new Set(selectedSetIds);
    if (next.has(setId)) next.delete(setId);
    else next.add(setId);
    selectedSetIds = next;
  }
  let selectedDistinctExercises = $derived(
    new Set(
      (session?.sets ?? [])
        .filter((s) => selectedSetIds.has(s.id))
        .map((s) => s.exercise_id),
    ).size,
  );
  async function confirmSuperset() {
    if (!session || selectedDistinctExercises < 2) return;
    // Assign the next free group id (mirrors the server's max+1) to each
    // selected Set via a patch op.
    const group = nextGroupId(session.sets);
    const ids = [...selectedSetIds];
    supersetMode = false;
    selectedSetIds = new Set();
    for (const id of ids) {
      await store.patchSet(id, { superset_group: group });
    }
  }
  async function ungroupSuperset(group: number) {
    if (!session) return;
    const ids = session.sets.filter((s) => s.superset_group === group).map((s) => s.id);
    for (const id of ids) {
      await store.patchSet(id, { superset_group: null });
    }
  }

  // Finish + delete: optimistic + queued, then navigate (no network wait).
  async function finish() {
    if (!session || finishing) return;
    finishing = true;
    await store.finish();
    await goto('/sessions');
  }

  async function deleteSession() {
    if (!session) return;
    if (!confirm('Delete this entire session and all its sets?')) return;
    await store.deleteSession();
    await goto('/sessions');
  }

  function flatIndex(setId: string): number {
    return session ? session.sets.findIndex((s) => s.id === setId) : -1;
  }
</script>

<div class="space-y-4 pb-44">
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
      <button class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm" onclick={() => store.load()}>Retry</button>
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
      <div class="flex items-center gap-1.5 shrink-0">
        <SyncIndicator />
        <button onclick={deleteSession} class="p-2 text-surface-500 hover:text-red-400 transition-colors" aria-label="Delete session">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
          </svg>
        </button>
      </div>
    </div>

    {#if error}
      <p class="text-sm text-red-400">{error}</p>
    {/if}

    <!-- Superset build toolbar -->
    {#if session.sets.length >= 2}
      <div class="flex items-center justify-between gap-2">
        {#if supersetMode}
          <p class="text-xs text-surface-400">
            Tap sets across 2+ exercises to alternate
            <span class="text-surface-500">({selectedSetIds.size} selected)</span>
          </p>
          <div class="flex gap-2">
            <button onclick={toggleSupersetMode} class="px-3 py-1.5 rounded-lg bg-surface-700 text-surface-300 text-xs font-medium">Cancel</button>
            <button onclick={confirmSuperset} disabled={selectedDistinctExercises < 2} class="px-3 py-1.5 rounded-lg bg-primary-500 text-white text-xs font-semibold disabled:opacity-40">Group superset</button>
          </div>
        {:else}
          <button onclick={toggleSupersetMode} class="inline-flex items-center gap-1.5 text-xs font-medium text-surface-400 hover:text-primary-300 transition-colors">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" /></svg>
            Make a superset
          </button>
        {/if}
      </div>
    {/if}

    <!-- Blocks: standalone exercise runs and superset alternation groups -->
    {#each blocks as block (block.kind === 'superset' ? `ss-${block.group}` : `ex-${block.exerciseId}-${block.sets[0].id}`)}
      {@const isSuper = block.kind === 'superset'}
      <div class="bg-surface-800 rounded-2xl border {isSuper ? 'border-violet-500/30' : 'border-surface-700'} overflow-hidden">
        <!-- Block header -->
        <div class="flex items-center justify-between px-4 py-3 border-b border-surface-700/70 {isSuper ? 'bg-violet-500/5' : ''}">
          {#if isSuper}
            <div class="min-w-0">
              <p class="text-[0.6rem] font-semibold uppercase tracking-wide text-violet-300 mb-0.5">Superset</p>
              <p class="text-sm font-semibold text-surface-100 truncate">
                {block.exerciseIds.map(exerciseName).join('  ↔  ')}
              </p>
            </div>
            <button onclick={() => ungroupSuperset(block.group)} class="text-xs text-surface-500 hover:text-surface-300 shrink-0" aria-label="Ungroup superset">Ungroup</button>
          {:else}
            <a href="/exercises/{block.exerciseId}" class="text-sm font-semibold text-surface-100 hover:text-primary-300 transition-colors truncate">
              {exerciseName(block.exerciseId)}
            </a>
            <div class="flex items-center gap-2 shrink-0">
              <button onclick={() => editRest(block.exerciseId)} class="inline-flex items-center gap-1 text-xs text-surface-500 hover:text-surface-300" aria-label="Edit rest duration">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                {restByExercise[block.exerciseId] ?? 120}s
              </button>
            </div>
          {/if}
        </div>

        <!-- Sets -->
        <div class="divide-y divide-surface-700/50">
          {#each block.sets as s, i (s.id)}
            {@const fi = flatIndex(s.id)}
            <div class="p-3 space-y-2.5 {supersetMode && selectedSetIds.has(s.id) ? 'bg-primary-500/10' : ''}">
              <div class="flex items-center gap-2">
                {#if supersetMode}
                  <button onclick={() => toggleSelect(s.id)} class="shrink-0 w-6 h-6 rounded-md border-2 flex items-center justify-center {selectedSetIds.has(s.id) ? 'bg-primary-500 border-primary-500 text-white' : 'border-surface-600 text-transparent'}" aria-label="Select set">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="3"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" /></svg>
                  </button>
                {:else}
                  <span class="shrink-0 w-6 h-6 rounded-full bg-surface-700 text-surface-300 text-xs flex items-center justify-center font-semibold">{i + 1}</span>
                {/if}

                {#if isSuper}
                  <span class="shrink-0 text-[0.65rem] font-medium text-violet-300/80 max-w-[4.5rem] truncate" title={s.exercise_name ?? ''}>{s.exercise_name}</span>
                {/if}

                <SetTypeChip value={s.set_type} onchange={(v: SetType) => patchSetNow(s.id, { set_type: v })} />

                <!-- Weight stepper -->
                <div class="flex items-center gap-1 flex-1">
                  <button onclick={() => stepWeight(s, -2.5)} class="w-8 h-8 rounded-lg bg-surface-700 text-surface-200 text-lg font-medium hover:bg-surface-600 active:bg-surface-500 transition-colors" aria-label="Decrease weight">−</button>
                  <div class="relative flex-1 min-w-0">
                    <input
                      type="number" inputmode="decimal" step="0.5" value={s.weight_kg}
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
                    type="number" inputmode="numeric" value={s.reps}
                    oninput={(e) => onRepsInput(s, e)}
                    class="w-12 text-center py-1.5 bg-surface-900 border border-surface-700 rounded-lg text-surface-100 text-sm font-semibold focus:outline-none focus:border-primary-500"
                    aria-label="Reps"
                  />
                  <button onclick={() => stepReps(s, 1)} class="w-8 h-8 rounded-lg bg-surface-700 text-surface-200 text-lg font-medium hover:bg-surface-600 active:bg-surface-500 transition-colors" aria-label="Increase reps">+</button>
                </div>
              </div>

              <!-- Effort + tools row -->
              <div class="flex items-center justify-between gap-2 pl-8">
                <EffortChips
                  value={s.effort_rir}
                  nudge={nudgeSetIds.has(s.id)}
                  onchange={(v: number | null) => patchSetNow(s.id, { effort_rir: v })}
                />
                <div class="flex items-center gap-0.5">
                  <button onclick={() => openCalc(s)} class="w-7 h-7 rounded-md text-surface-500 hover:text-primary-300 hover:bg-surface-700 transition-colors" aria-label="Plate calculator">
                    <svg class="w-4 h-4 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M9 4.5v15m6-15v15M3.75 9h16.5M3.75 15h16.5" /></svg>
                  </button>
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
          onclick={() => addAnotherSet(block.sets[block.sets.length - 1], isSuper ? block.group : null)}
          class="w-full py-2.5 text-sm font-medium {isSuper ? 'text-violet-300 hover:bg-violet-500/10' : 'text-primary-300 hover:bg-primary-500/10'} transition-colors border-t border-surface-700/70"
        >
          {#if isSuper}
            + Next ({exerciseName(nextSupersetExerciseId(session.sets, block.sets[block.sets.length - 1].id) ?? block.sets[block.sets.length - 1].exercise_id)})
          {:else}
            + Add set
          {/if}
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

    {#if blocks.length === 0}
      <p class="text-center text-sm text-surface-500 pt-2">Add your first exercise to start logging sets.</p>
    {/if}
  {/if}
</div>

<!-- Rest timer + finish bar (active sessions), above the bottom nav -->
{#if session?.is_active}
  <div class="fixed bottom-[calc(3.5rem+env(safe-area-inset-bottom))] lg:bottom-0 inset-x-0 z-20 p-3 space-y-2 bg-gradient-to-t from-surface-950 via-surface-950/95 to-transparent">
    <div class="max-w-3xl mx-auto lg:pl-64 space-y-2">
      <RestTimer startSignal={restSignal} startDuration={restDuration} />
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

<PlateCalculator
  open={calcOpen}
  weightKg={calcWeight}
  reps={calcReps}
  equipment={plateEquipment}
  onclose={() => (calcOpen = false)}
/>

<PRCelebration prs={celebratedPrs} onclose={() => (celebratedPrs = [])} />
