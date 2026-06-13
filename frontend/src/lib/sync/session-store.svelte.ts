/**
 * Offline-first data layer for a single live Session (ADR-0005, #6).
 *
 * The logging screen binds to THIS instead of calling `api` directly. Every
 * mutation:
 *   1. updates the optimistic snapshot immediately (the UI never waits on the
 *      network), then
 *   2. enqueues a {@link SyncOp} via the sync engine (durably persisted to
 *      IndexedDB, drained to the API when online).
 *
 * Ids are minted client-side (`newId`) so a Set logged at the gym already has
 * its final id — the optimistic id IS the server id, no remap on sync. PR
 * detection stays in the component (it already mirrors the backend, `lib/pr.ts`)
 * and fires off the optimistic snapshot, so it works offline.
 *
 * Reconcile: when the engine finishes a drain touching this Session, we re-fetch
 * the authoritative snapshot (if online) and merge it with any still-pending
 * ops (LWW) — so server PRs / counted volume settle without clobbering an edit
 * the user just made that hasn't drained yet.
 */

import { ApiError, api } from '$lib/api';
import type {
  SessionDetail,
  SetCreate,
  SetType,
  SetUpdate,
  TrainingSet,
} from '$lib/types';
import { drain, enqueueOp, onDrained } from './engine';
import {
  type SessionSnapshot,
  type SyncOp,
  applyOp,
  newOpId,
  reconcileServerSession,
} from './queue';
import {
  deleteSnapshot,
  getSnapshot,
  loadOps,
  putSnapshot,
} from './store';

/** A fresh client-side UUID for a new Session or Set. */
export function newId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  // Fallback (older engines): RFC-4122-ish v4 from Math.random — fine as a
  // last resort; collision risk is negligible for a single-user device.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0;
    const v = ch === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

function nowISO(): string {
  return new Date().toISOString();
}

/** A {@link SyncOp} variant with its `opId` omitted (distributes over the union). */
type SyncOpDraft = SyncOp extends infer O
  ? O extends { opId: string }
    ? Omit<O, 'opId'>
    : never
  : never;

/** Stamp a fresh `opId` on a drafted op, preserving its variant shape. */
function makeOp(draft: SyncOpDraft): SyncOp {
  return { opId: newOpId(), ...draft } as SyncOp;
}

/**
 * Create a reactive, offline-first store for one Session id. Svelte 5 runes
 * factory (the repo pattern): private `$state`, exposed via getters + methods.
 */
export function createSessionStore(sessionId: string) {
  let snapshot = $state<SessionSnapshot | null>(null);
  let loading = $state(true);
  let notFound = $state(false);
  // Pending ops for THIS session, kept so a server reconcile re-applies them.
  let pendingForSession = $state<SyncOp[]>([]);

  async function refreshPending() {
    try {
      const all = await loadOps();
      pendingForSession = all.filter((o) => o.sessionId === sessionId);
    } catch {
      pendingForSession = [];
    }
  }

  /**
   * Load the Session: prefer the network (authoritative), fall back to the
   * cached snapshot replayed with pending ops when offline. Either way the
   * optimistic view ends up in `snapshot`.
   */
  async function load() {
    loading = true;
    notFound = false;
    await refreshPending();
    try {
      const server = await api.get<SessionDetail>(`/api/sessions/${sessionId}`);
      await putSnapshot(server);
      snapshot = reconcileServerSession(server, pendingForSession);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        // Not on the server. It may be a Session born offline that hasn't
        // synced yet — rebuild from the cached snapshot + pending ops.
        const cached = await getSnapshot(sessionId);
        const rebuilt = cached
          ? reconcileServerSession(cached, pendingForSession)
          : replayFromScratch();
        if (rebuilt) snapshot = rebuilt;
        else notFound = true;
      } else {
        // Network/other error (likely offline): use cache + pending ops.
        const cached = await getSnapshot(sessionId);
        snapshot = cached
          ? reconcileServerSession(cached, pendingForSession)
          : replayFromScratch();
      }
    } finally {
      loading = false;
    }
  }

  /** Rebuild a Session that exists only as queued ops (born fully offline). */
  function replayFromScratch(): SessionSnapshot | null {
    let snap: SessionSnapshot | null = null;
    for (const op of pendingForSession) snap = applyOp(snap, op);
    return snap;
  }

  // Re-fetch authoritative state after a drain that touched this Session.
  const unsub = onDrained(async (touched) => {
    if (!touched.has(sessionId)) return;
    await refreshPending();
    try {
      const server = await api.get<SessionDetail>(`/api/sessions/${sessionId}`);
      await putSnapshot(server);
      snapshot = reconcileServerSession(server, pendingForSession);
    } catch {
      // Stay on the optimistic view if the reconcile fetch fails.
    }
  });

  /** Apply an op optimistically to the local snapshot, then enqueue it. */
  async function dispatch(op: SyncOp) {
    snapshot = applyOp(snapshot, op);
    pendingForSession = [...pendingForSession, op];
    if (snapshot) await putSnapshot(snapshot); // cache optimistic state too
    await enqueueOp(op);
  }

  return {
    get snapshot() {
      return snapshot;
    },
    get loading() {
      return loading;
    },
    get notFound() {
      return notFound;
    },
    load,
    destroy() {
      unsub();
    },

    /** Add a Set (client-minted id); returns the new set id. */
    async addSet(payload: SetCreate): Promise<string> {
      const id = newId();
      const set: TrainingSet = {
        id,
        exercise_id: payload.exercise_id,
        order_index: snapshot ? snapshot.sets.length : 0,
        weight_kg: payload.weight_kg,
        reps: payload.reps,
        set_type: payload.set_type ?? 'normal',
        effort_rir: payload.effort_rir ?? null,
        superset_group: payload.superset_group ?? null,
        // The picker passes the name through `addExercise`; fall back to an
        // existing set's name for this exercise so the header reads right offline.
        exercise_name:
          snapshot?.sets.find((s) => s.exercise_id === payload.exercise_id)
            ?.exercise_name ?? null,
      };
      await dispatch(makeOp({ kind: 'addSet', sessionId, payload: set }));
      return id;
    },

    /**
     * Optimistically reflect a patch on the snapshot WITHOUT enqueuing an op —
     * for the live stepper, where the value must move instantly but we debounce
     * the durable write (otherwise dragging would mint dozens of ops). Pair with
     * a debounced {@link patchSet} carrying the final value.
     */
    previewPatch(setId: string, changes: SetUpdate) {
      const preview = makeOp({ kind: 'patchSet', sessionId, setId, payload: changes });
      snapshot = applyOp(snapshot, preview);
    },

    /** Patch a Set (only sent fields change); optimistic + enqueued. */
    async patchSet(setId: string, changes: SetUpdate): Promise<void> {
      await dispatch(
        makeOp({ kind: 'patchSet', sessionId, setId, payload: changes }),
      );
    },

    async deleteSet(setId: string): Promise<void> {
      await dispatch(makeOp({ kind: 'deleteSet', sessionId, setId }));
    },

    async reorder(setIds: string[]): Promise<void> {
      await dispatch(
        makeOp({ kind: 'reorderSets', sessionId, payload: { set_ids: setIds } }),
      );
    },

    async finish(): Promise<void> {
      await dispatch(
        makeOp({ kind: 'finishSession', sessionId, payload: { ended_at: nowISO() } }),
      );
    },

    async deleteSession(): Promise<void> {
      snapshot = null;
      await deleteSnapshot(sessionId);
      await enqueueOp(makeOp({ kind: 'deleteSession', sessionId }));
    },

    /** Set the displayed exercise name on freshly-added sets (offline header). */
    setExerciseName(exerciseId: string, name: string) {
      if (!snapshot) return;
      snapshot = {
        ...snapshot,
        sets: snapshot.sets.map((s) =>
          s.exercise_id === exerciseId && s.exercise_name == null
            ? { ...s, exercise_name: name }
            : s,
        ),
      };
    },
  };
}

export type SessionStore = ReturnType<typeof createSessionStore>;

/** Trigger a drain (e.g. a manual "retry" tap on the indicator). */
export function syncNow(): void {
  void drain();
}

/**
 * Set a SetType helper re-export so callers don't reach into queue internals.
 * (Kept tiny; the component already imports SetType from types.)
 */
export type { SetType };
