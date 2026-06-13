/**
 * The sync engine (ADR-0005, #6) — drains the offline op queue to the API.
 *
 * Ties together the pure queue logic (`queue.ts`), IndexedDB persistence
 * (`store.ts`), the HTTP client (`api.ts`) and the reactive sync-state
 * (`sync-state.svelte.ts`). Responsibilities:
 *
 *   - Own the in-memory op queue (mirrored to IndexedDB) and accept enqueues.
 *   - Drain the queue to `/api/sessions...` in strict FIFO order whenever we're
 *     online — on `enqueue`, on the `online` event, and once on app load.
 *   - Preserve order: stop at the first op that can't be delivered (network
 *     down) and retry the whole tail later; never reorder or skip ahead.
 *   - Idempotent + LWW: ops carry client-minted ids and the server `add_set` is
 *     idempotent, so re-sending after a flaky response is safe.
 *   - Drop an op only on a *permanent* client error (4xx that re-sending can't
 *     fix), so one poisoned op never wedges the queue forever.
 *
 * Optimistic state is owned by the per-session data layer (`session-store`),
 * which subscribes via `onDrained` to refresh authoritative snapshots after a
 * successful drain (so server PRs / volume reconcile).
 */

import { ApiError, api } from '$lib/api';
import type { SessionDetail } from '$lib/types';
import {
  collapseQueue,
  reorderForSend,
  type SyncOp,
} from './queue';
import {
  countOps,
  loadOps,
  persistOp,
  putSnapshot,
  removeOp,
  replaceQueue,
} from './store';
import { syncState } from './sync-state.svelte';

// In-memory mirror of the durable queue, in FIFO order.
let queue: SyncOp[] = [];
let loaded = false;
let draining = false;
let listenersBound = false;

type DrainListener = (syncedSessionIds: Set<string>) => void;
const drainListeners = new Set<DrainListener>();

/** Subscribe to "a drain just finished"; receives the session ids it touched. */
export function onDrained(fn: DrainListener): () => void {
  drainListeners.add(fn);
  return () => drainListeners.delete(fn);
}

function isOnline(): boolean {
  return typeof navigator === 'undefined' ? true : navigator.onLine;
}

function refreshPending(): void {
  syncState.setPending(queue.length);
}

/** Load the persisted queue once, then bind connectivity listeners. */
export async function initSyncEngine(): Promise<void> {
  if (loaded) return;
  loaded = true;
  syncState.setOnline(isOnline());
  try {
    queue = await loadOps();
  } catch {
    queue = [];
  }
  refreshPending();
  bindListeners();
  void drain();
}

function bindListeners(): void {
  if (listenersBound || typeof window === 'undefined') return;
  listenersBound = true;
  window.addEventListener('online', () => {
    syncState.setOnline(true);
    void drain();
  });
  window.addEventListener('offline', () => {
    syncState.setOnline(false);
  });
}

/**
 * Enqueue an op: persist it durably, mirror it in memory, then try to drain.
 * Returns once persisted (so the caller knows it's safe), not once synced.
 */
export async function enqueueOp(op: SyncOp): Promise<void> {
  queue = [...queue, op];
  refreshPending();
  await persistOp(op);
  void drain();
}

/**
 * Collapse the in-memory + durable queue (drop ops that cancel out before
 * draining). Safe to call before a drain; replay-invariant.
 */
async function collapse(): Promise<void> {
  const collapsed = collapseQueue(queue);
  if (collapsed.length !== queue.length) {
    queue = collapsed;
    await replaceQueue(collapsed);
    refreshPending();
  }
}

/**
 * Send a single op to its endpoint. Resolves with the server response (when
 * one is useful) or undefined. Throws on failure — the caller decides whether
 * to retry (network) or drop (permanent 4xx).
 */
async function sendOp(op: SyncOp): Promise<SessionDetail | void> {
  switch (op.kind) {
    case 'startSession':
      return api.post<SessionDetail>('/api/sessions/', {
        id: op.sessionId,
        started_at: op.payload.started_at,
      });
    case 'addSet':
      await api.post(`/api/sessions/${op.sessionId}/sets`, {
        id: op.payload.id,
        exercise_id: op.payload.exercise_id,
        weight_kg: op.payload.weight_kg,
        reps: op.payload.reps,
        effort_rir: op.payload.effort_rir,
        set_type: op.payload.set_type,
        superset_group: op.payload.superset_group ?? undefined,
      });
      return;
    case 'patchSet':
      await api.patch(
        `/api/sessions/${op.sessionId}/sets/${op.setId}`,
        op.payload,
      );
      return;
    case 'deleteSet':
      await api.delete(`/api/sessions/${op.sessionId}/sets/${op.setId}`);
      return;
    case 'reorderSets':
      return api.put<SessionDetail>(
        `/api/sessions/${op.sessionId}/sets/order`,
        { set_ids: op.payload.set_ids },
      );
    case 'finishSession':
      // Send the client's finish time so a later sync records when the user
      // actually finished (not server-receipt time) and the end time doesn't
      // flicker to the server clock on reconcile.
      return api.post<SessionDetail>(`/api/sessions/${op.sessionId}/finish`, {
        ended_at: op.payload.ended_at,
      });
    case 'deleteSession':
      await api.delete(`/api/sessions/${op.sessionId}`);
      return;
  }
}

/**
 * A client (4xx) error that re-sending can never fix → drop the op so it stops
 * wedging the queue. We DON'T treat 404 as permanent for a delete (the record
 * may simply be gone already — that's success), but a 404 on a non-delete means
 * the parent Session/Set isn't there to mutate, which a retry won't fix.
 *
 * 5xx and network/offline errors are transient → keep the op and retry.
 */
function isPermanent(err: unknown, op: SyncOp): boolean {
  if (!(err instanceof ApiError)) return false; // network error → transient
  const s = err.status;
  if (s === 404 && (op.kind === 'deleteSet' || op.kind === 'deleteSession')) {
    return true; // already gone == done; drop it
  }
  return s >= 400 && s < 500;
}

/**
 * Drain the queue head-first while online. Stops at the first transient
 * failure (retried on the next trigger). Notifies `onDrained` listeners with
 * the set of session ids whose ops were delivered, so they can re-fetch
 * authoritative snapshots.
 */
export async function drain(): Promise<void> {
  if (draining) return;
  if (!isOnline()) {
    syncState.setOnline(false);
    return;
  }
  if (queue.length === 0) {
    syncState.setSyncing(false);
    syncState.setErrored(false);
    return;
  }

  draining = true;
  syncState.setSyncing(true);
  const touched = new Set<string>();

  try {
    await collapse();

    // Ops sent earlier in THIS pass, in order — used to re-derive a reorder's
    // set_ids against deletes that already went out (so it stays a valid
    // permutation of what the server now holds; see `reorderForSend`).
    const processed: SyncOp[] = [];

    // Walk a snapshot of the queue head-first. Each delivered op is removed
    // from both mirrors; a transient failure stops the walk (order preserved).
    while (queue.length > 0) {
      if (!isOnline()) break;
      const head = queue[0];
      // For a reorder, strip ids that earlier-drained deletes already removed.
      const op =
        head.kind === 'reorderSets' ? reorderForSend(head, processed) : head;
      try {
        const res = await sendOp(op);
        touched.add(op.sessionId);
        // The finish/reorder/start responses are authoritative snapshots —
        // cache them so a reload reflects server truth immediately.
        if (res && typeof res === 'object' && 'sets' in res) {
          await putSnapshot(res as SessionDetail);
        }
      } catch (err) {
        if (isPermanent(err, op)) {
          // Drop the poisoned op and keep going so it can't wedge the queue.
          touched.add(op.sessionId);
        } else {
          // Transient (offline / 5xx): stop and retry the whole tail later.
          syncState.setErrored(true);
          break;
        }
      }
      // Delivered or dropped-permanent: record it (so a later reorder can be
      // re-derived against it) and remove the head from both mirrors.
      processed.push(head);
      queue = queue.slice(1);
      await removeOp(head.opId);
      refreshPending();
    }

    if (queue.length === 0) syncState.setErrored(false);
  } finally {
    draining = false;
    syncState.setSyncing(false);
    refreshPending();
  }

  if (touched.size > 0) {
    for (const fn of drainListeners) fn(touched);
  }

  // If new ops arrived during the drain and we're still online, go again.
  if (queue.length > 0 && isOnline() && !syncState.errored) {
    void drain();
  }
}

/** Current pending-op count (reads the durable store; for diagnostics). */
export async function pendingCount(): Promise<number> {
  return countOps();
}

/** Test/diagnostic hook: the in-memory queue length. */
export function queueLength(): number {
  return queue.length;
}
