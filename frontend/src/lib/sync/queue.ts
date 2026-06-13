/**
 * The PURE offline sync core — queue, replay, collapse, reconcile (ADR-0005).
 *
 * Gyms are connectivity dead zones, so the Session-logging surface is offline-
 * first: every mutation (start a Session, add/patch/delete a Set, reorder,
 * finish, delete) is captured locally and replayed to `/api/sessions...` when
 * connectivity returns. This module is the deterministic data layer underneath
 * that — NO IndexedDB, NO network, NO `Date.now()` baked in (callers inject
 * timestamps). The IO (IndexedDB persistence in `store.ts`, draining in
 * `engine.ts`) wraps these pure functions, which is what the vitest suite
 * (`queue.test.ts`) exercises without a browser.
 *
 * Design decisions (documented for future readers):
 *
 *  - **Client-generated ids.** The client mints the Session and Set UUIDs up
 *    front (the backend was extended to accept a supplied `id`; ADR-0005,
 *    slice #6). The optimistic local id therefore IS the server id — there is
 *    no id-remap step on sync, which is what makes a queued `addSet` followed
 *    by `patchSet`/`deleteSet` on the same id replay trivially.
 *
 *  - **FIFO op log.** A `SyncOp[]` is an ordered log; `applyOps` folds it onto
 *    a base snapshot to produce the optimistic view the UI binds to. The
 *    network layer drains the same list head-first, so order is preserved.
 *
 *  - **Last-write-wins per record.** Single-device (accounts are isolated,
 *    ADR-0003; a user logs from one device at a time), so LWW is correct and
 *    needs no CRDT. The queue order *is* the causal order; the last write to a
 *    field wins both in the optimistic replay and after server reconcile.
 *
 *  - **Collapse.** `collapseQueue` drops ops that cancel out before draining —
 *    a Set created then deleted while still offline (never synced) has its
 *    whole add/patch/delete trio removed, and patches to a still-local created
 *    Set fold into the create. This avoids replaying churn and, crucially,
 *    avoids sending a `deleteSet`/`patchSet` for an id the server never saw.
 *    Collapsing is replay-invariant: it yields the same snapshot as the raw
 *    queue (a property the tests assert).
 *
 *  - **Idempotent replay.** Because ids are client-supplied and `add_set` is
 *    idempotent server-side, re-sending an op after a flaky response never
 *    double-applies.
 */

import type { SessionDetail, SetType, TrainingSet } from '$lib/types';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * A local, optimistic view of a Session — structurally the same shape the API
 * returns (`SessionDetail`), so the UI binds to it identically whether the data
 * is server-fresh or replayed-from-queue.
 */
export type SessionSnapshot = SessionDetail;

/** Fields a queued create carries for a new Session. */
export interface StartSessionPayload {
  started_at: string;
}

/** Fields a queued finish carries. */
export interface FinishSessionPayload {
  ended_at: string;
}

/** A reorder op's payload: the full set-id list in the desired order. */
export interface ReorderPayload {
  set_ids: string[];
}

/** A patch op's payload: only the fields that changed (others untouched). */
export interface PatchSetPayload {
  weight_kg?: number;
  reps?: number;
  effort_rir?: number | null;
  set_type?: SetType;
  superset_group?: number | null;
}

/**
 * One queued mutation. Discriminated on `kind`; `sessionId` scopes every op to
 * its Session (collapse/reconcile never cross sessions). `opId` is a unique,
 * stable handle the IO layer uses to mark an op synced.
 */
export type SyncOp =
  | { opId: string; kind: 'startSession'; sessionId: string; payload: StartSessionPayload }
  | { opId: string; kind: 'addSet'; sessionId: string; payload: TrainingSet }
  | { opId: string; kind: 'patchSet'; sessionId: string; setId: string; payload: PatchSetPayload }
  | { opId: string; kind: 'deleteSet'; sessionId: string; setId: string }
  | { opId: string; kind: 'reorderSets'; sessionId: string; payload: ReorderPayload }
  | { opId: string; kind: 'finishSession'; sessionId: string; payload: FinishSessionPayload }
  | { opId: string; kind: 'deleteSession'; sessionId: string };

export type SyncOpKind = SyncOp['kind'];

// ---------------------------------------------------------------------------
// Op id
// ---------------------------------------------------------------------------

let opCounter = 0;

/**
 * A unique op id. Prefers `crypto.randomUUID()` when present (browser + modern
 * node); falls back to a monotonic counter + random suffix so the pure core
 * never depends on the platform. Uniqueness is all that matters here.
 */
export function newOpId(): string {
  const c = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (c?.randomUUID) return c.randomUUID();
  opCounter += 1;
  return `op-${Date.now().toString(36)}-${opCounter}-${Math.random().toString(36).slice(2, 10)}`;
}

// ---------------------------------------------------------------------------
// Volume (mirror of the backend exclusion: only `normal` sets count)
// ---------------------------------------------------------------------------

function countsForVolume(setType: SetType): boolean {
  return setType === 'normal';
}

function sumVolume(sets: TrainingSet[]): number {
  return sets.reduce(
    (acc, s) => (countsForVolume(s.set_type) ? acc + s.weight_kg * s.reps : acc),
    0,
  );
}

// ---------------------------------------------------------------------------
// Order compaction
// ---------------------------------------------------------------------------

/**
 * Return the sets sorted by their current `order_index` and re-stamped 0-based
 * gap-free — the same invariant the server keeps (append on add, compact on
 * delete, rewrite on reorder). Pure; returns new set objects.
 */
export function compactSetOrder(sets: TrainingSet[]): TrainingSet[] {
  return [...sets]
    .sort((a, b) => a.order_index - b.order_index)
    .map((s, i) => (s.order_index === i ? s : { ...s, order_index: i }));
}

// ---------------------------------------------------------------------------
// Queue ops
// ---------------------------------------------------------------------------

/** Append an op to the queue immutably (FIFO). */
export function enqueue(queue: SyncOp[], op: SyncOp): SyncOp[] {
  return [...queue, op];
}

/** Serialize the queue for IndexedDB / localStorage (plain JSON). */
export function serializeQueue(queue: SyncOp[]): string {
  return JSON.stringify(queue);
}

/** Restore a queue from its serialized form. */
export function deserializeQueue(json: string): SyncOp[] {
  if (!json) return [];
  const parsed = JSON.parse(json);
  return Array.isArray(parsed) ? (parsed as SyncOp[]) : [];
}

// ---------------------------------------------------------------------------
// Replay
// ---------------------------------------------------------------------------

function withDerived(snap: SessionSnapshot): SessionSnapshot {
  const sets = compactSetOrder(snap.sets);
  return {
    ...snap,
    sets,
    set_count: sets.length,
    total_volume_kg: sumVolume(sets),
    is_active: snap.ended_at === null,
  };
}

/**
 * Apply a single op to a (possibly null) snapshot, returning the next snapshot.
 *
 * Returns `null` when the op removes the Session (`deleteSession`) or targets a
 * different Session. A `startSession` materializes an empty active Session.
 * Patch/delete against an unknown Set is a harmless no-op (the set may have been
 * collapsed away, or this op arrived before its create on a different replay).
 */
export function applyOp(
  snapshot: SessionSnapshot | null,
  op: SyncOp,
): SessionSnapshot | null {
  switch (op.kind) {
    case 'startSession': {
      // Idempotent: if a snapshot already exists for this session, keep it.
      if (snapshot && snapshot.id === op.sessionId) return snapshot;
      return withDerived({
        id: op.sessionId,
        started_at: op.payload.started_at,
        ended_at: null,
        is_active: true,
        set_count: 0,
        total_volume_kg: 0,
        sets: [],
      });
    }
    case 'deleteSession':
      return null;
    default:
      break;
  }

  if (snapshot === null) return null;

  switch (op.kind) {
    case 'addSet': {
      // Idempotent: re-adding a known id replaces it rather than duplicating.
      const without = snapshot.sets.filter((s) => s.id !== op.payload.id);
      const nextIndex = without.length;
      const set: TrainingSet = { ...op.payload, order_index: nextIndex };
      return withDerived({ ...snapshot, sets: [...without, set] });
    }
    case 'patchSet': {
      const sets = snapshot.sets.map((s) =>
        s.id === op.setId ? applyPatch(s, op.payload) : s,
      );
      return withDerived({ ...snapshot, sets });
    }
    case 'deleteSet': {
      const sets = snapshot.sets.filter((s) => s.id !== op.setId);
      return withDerived({ ...snapshot, sets });
    }
    case 'reorderSets': {
      const byId = new Map(snapshot.sets.map((s) => [s.id, s]));
      const ordered: TrainingSet[] = [];
      op.payload.set_ids.forEach((sid, i) => {
        const s = byId.get(sid);
        if (s) ordered.push({ ...s, order_index: i });
      });
      // Append any sets not named in the list (defensive — keeps them, ordered).
      for (const s of snapshot.sets) {
        if (!op.payload.set_ids.includes(s.id)) ordered.push(s);
      }
      return withDerived({ ...snapshot, sets: ordered });
    }
    case 'finishSession':
      return withDerived({ ...snapshot, ended_at: op.payload.ended_at });
    default:
      return snapshot;
  }
}

/** Merge a patch payload onto a set (only present fields change). */
function applyPatch(set: TrainingSet, patch: PatchSetPayload): TrainingSet {
  const next = { ...set };
  if ('weight_kg' in patch && patch.weight_kg !== undefined) next.weight_kg = patch.weight_kg;
  if ('reps' in patch && patch.reps !== undefined) next.reps = patch.reps;
  if ('effort_rir' in patch) next.effort_rir = patch.effort_rir ?? null;
  if ('set_type' in patch && patch.set_type !== undefined) next.set_type = patch.set_type;
  if ('superset_group' in patch) next.superset_group = patch.superset_group ?? null;
  return next;
}

/**
 * Fold an ordered op list onto a base snapshot, returning the optimistic view.
 *
 * `base` is the last authoritative server snapshot for the session (or
 * `undefined`/`null` for a session born offline). `sessionId` scopes the replay
 * — ops for other sessions are ignored. Returns `null` if the session ends up
 * deleted or never started.
 */
export function applyOps(
  base: SessionSnapshot | null | undefined,
  ops: SyncOp[],
  sessionId: string,
): SessionSnapshot | null {
  let snapshot: SessionSnapshot | null = base ? withDerived(base) : null;
  for (const op of ops) {
    if (op.sessionId !== sessionId) continue;
    snapshot = applyOp(snapshot, op);
  }
  return snapshot;
}

// ---------------------------------------------------------------------------
// Collapse
// ---------------------------------------------------------------------------

/**
 * Collapse a queue before draining: remove ops that cancel out and fold patches
 * into still-local creates. Replay-invariant — `applyOps(collapseQueue(q)) ===
 * applyOps(q)` for every session (asserted by the tests).
 *
 * Rules, per session:
 *  - If a Set is BOTH created (`addSet`) and deleted (`deleteSet`) in the queue
 *    (never synced), drop the create, the delete, and every patch to it.
 *  - Otherwise, fold each `patchSet` whose target was created in the queue into
 *    that create's payload (so the create lands with final values), and drop the
 *    patch. Patches to server-known sets are kept (they must replay).
 *  - If a Session is BOTH started (`startSession`) and deleted (`deleteSession`)
 *    in the queue, drop every op for that session.
 */
export function collapseQueue(queue: SyncOp[]): SyncOp[] {
  // 1. Sessions started AND deleted within the queue vanish entirely.
  const startedSessions = new Set<string>();
  const deletedSessions = new Set<string>();
  for (const op of queue) {
    if (op.kind === 'startSession') startedSessions.add(op.sessionId);
    if (op.kind === 'deleteSession') deletedSessions.add(op.sessionId);
  }
  const droppedSessions = new Set(
    [...startedSessions].filter((s) => deletedSessions.has(s)),
  );

  const afterSessions = queue.filter((op) => !droppedSessions.has(op.sessionId));

  // 2. Per (session, set): was the set created in the (surviving) queue, and
  //    was it later deleted? Key includes sessionId so identical set-id strings
  //    in different sessions never interfere.
  const setKey = (sessionId: string, setId: string) => `${sessionId} ${setId}`;
  const createdSets = new Set<string>();
  const deletedSets = new Set<string>();
  for (const op of afterSessions) {
    if (op.kind === 'addSet') createdSets.add(setKey(op.sessionId, op.payload.id));
    if (op.kind === 'deleteSet') deletedSets.add(setKey(op.sessionId, op.setId));
  }
  // Sets that were created locally AND deleted locally → drop their whole trio.
  const droppedSets = new Set(
    [...createdSets].filter((k) => deletedSets.has(k)),
  );

  // 3. Fold patches into local creates. Walk once, mutating create payloads in a
  //    working copy; drop folded patches and any op for a dropped set.
  const result: SyncOp[] = [];
  // Map a surviving create's set-key → its index in `result`, so a later patch
  // can fold into it.
  const createIndexByKey = new Map<string, number>();

  for (const op of afterSessions) {
    switch (op.kind) {
      case 'addSet': {
        const key = setKey(op.sessionId, op.payload.id);
        if (droppedSets.has(key)) continue; // created-then-deleted: gone
        // Clone the payload so folding doesn't mutate the caller's op.
        const cloned: SyncOp = { ...op, payload: { ...op.payload } };
        createIndexByKey.set(key, result.length);
        result.push(cloned);
        break;
      }
      case 'patchSet': {
        const key = setKey(op.sessionId, op.setId);
        if (droppedSets.has(key)) continue; // target gone
        const createIdx = createIndexByKey.get(key);
        if (createIdx !== undefined) {
          // Fold into the local create's payload; drop the patch.
          const createOp = result[createIdx];
          if (createOp.kind === 'addSet') {
            createOp.payload = applyPatch(createOp.payload, op.payload);
          }
          continue;
        }
        result.push(op); // server-known set: keep the patch
        break;
      }
      case 'deleteSet': {
        const key = setKey(op.sessionId, op.setId);
        if (droppedSets.has(key)) continue; // local create+delete: gone
        result.push(op); // real delete of a server-known set
        break;
      }
      default:
        result.push(op);
        break;
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Reconcile
// ---------------------------------------------------------------------------

/**
 * Merge an authoritative server snapshot with the ops still pending for that
 * session, re-applying the pending ops on top (last-write-wins until they
 * sync). With no pending ops the server snapshot wins outright.
 *
 * Used after a fetch/sync: the server is the record of truth, but a local edit
 * the user just made that hasn't drained yet must not flicker back to the old
 * value — so we layer the unsynced ops over the fresh base.
 */
export function reconcileServerSession(
  server: SessionDetail,
  pendingOps: SyncOp[],
): SessionSnapshot {
  const merged = applyOps(server, pendingOps, server.id);
  // A pending deleteSession would null this out; callers handle that separately,
  // so fall back to the server snapshot if replay removed it.
  return merged ?? withDerived(server);
}
