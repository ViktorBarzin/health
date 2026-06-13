import { beforeEach, describe, expect, it } from 'vitest';
import {
  type SessionSnapshot,
  type SyncOp,
  applyOp,
  applyOps,
  collapseQueue,
  compactSetOrder,
  enqueue,
  newOpId,
  reconcileServerSession,
  serializeQueue,
  deserializeQueue,
} from './queue';
import type { SessionDetail, TrainingSet } from '$lib/types';

// ---------------------------------------------------------------------------
// The PURE offline sync core (ADR-0005). No IndexedDB, no network, no clock
// beyond what callers inject — just the queue+replay+reconcile data logic the
// IndexedDB/network IO layers wrap. Everything here is deterministic and unit-
// testable in node, which is the must-have given the no-browser constraint.
//
// Mental model:
//   * The client generates the Session/Set UUIDs up front, so the OPTIMISTIC
//     id IS the server id — no remap on sync.
//   * A SyncOp queue is an ordered (FIFO) log of mutations. `applyOps` replays
//     it onto a base snapshot to get the optimistic view the UI binds to.
//   * `collapseQueue` drops ops that cancel out (a set created then deleted
//     while still offline) so we don't replay churn — LWW per record falls out.
//   * `reconcileServerSession` merges an authoritative server snapshot back
//     while still-pending local ops are re-applied on top (last write wins).
// ---------------------------------------------------------------------------

let seq = 0;
function id(prefix: string): string {
  seq += 1;
  return `${prefix}-${String(seq).padStart(4, '0')}`;
}

beforeEach(() => {
  seq = 0;
});

function emptySnapshot(sessionId: string, startedAt = '2026-06-13T10:00:00Z'): SessionSnapshot {
  return {
    id: sessionId,
    started_at: startedAt,
    ended_at: null,
    is_active: true,
    set_count: 0,
    total_volume_kg: 0,
    sets: [],
  };
}

function makeSet(overrides: Partial<TrainingSet> & { id: string; exercise_id: string }): TrainingSet {
  return {
    order_index: 0,
    weight_kg: 100,
    reps: 5,
    set_type: 'normal',
    effort_rir: null,
    superset_group: null,
    exercise_name: null,
    ...overrides,
  };
}

// A start op + the snapshot it produces, used by most tests.
function startOp(sessionId: string): SyncOp {
  return {
    opId: newOpId(),
    kind: 'startSession',
    sessionId,
    payload: { started_at: '2026-06-13T10:00:00Z' },
  };
}

function addSetOp(sessionId: string, set: TrainingSet): SyncOp {
  return {
    opId: newOpId(),
    kind: 'addSet',
    sessionId,
    payload: set,
  };
}

describe('newOpId', () => {
  it('produces unique ids', () => {
    const ids = new Set(Array.from({ length: 1000 }, () => newOpId()));
    expect(ids.size).toBe(1000);
  });
});

describe('enqueue', () => {
  it('appends ops in FIFO order (immutably)', () => {
    const a = startOp('s1');
    const b = addSetOp('s1', makeSet({ id: 'set1', exercise_id: 'ex1' }));
    const q0: SyncOp[] = [];
    const q1 = enqueue(q0, a);
    const q2 = enqueue(q1, b);
    expect(q0).toEqual([]); // original untouched
    expect(q2.map((o) => o.opId)).toEqual([a.opId, b.opId]);
  });
});

describe('applyOp / applyOps — optimistic replay', () => {
  it('startSession on an empty base creates the active session snapshot', () => {
    const sid = 's1';
    const snap = applyOps(undefined, [startOp(sid)], sid);
    expect(snap).not.toBeNull();
    expect(snap!.id).toBe(sid);
    expect(snap!.is_active).toBe(true);
    expect(snap!.ended_at).toBeNull();
    expect(snap!.sets).toEqual([]);
  });

  it('addSet appends a set and bumps order_index gap-free', () => {
    const sid = 's1';
    const ops = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1' })),
      addSetOp(sid, makeSet({ id: 'b', exercise_id: 'ex1' })),
      addSetOp(sid, makeSet({ id: 'c', exercise_id: 'ex2' })),
    ];
    const snap = applyOps(undefined, ops, sid)!;
    expect(snap.sets.map((s) => s.id)).toEqual(['a', 'b', 'c']);
    expect(snap.sets.map((s) => s.order_index)).toEqual([0, 1, 2]);
    expect(snap.set_count).toBe(3);
  });

  it('patchSet changes only the sent fields (last write wins on a field)', () => {
    const sid = 's1';
    const ops: SyncOp[] = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1', weight_kg: 100, reps: 5 })),
      { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { weight_kg: 110 } },
      { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { reps: 3 } },
      { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { weight_kg: 120 } },
    ];
    const snap = applyOps(undefined, ops, sid)!;
    const a = snap.sets.find((s) => s.id === 'a')!;
    expect(a.weight_kg).toBe(120); // last weight write wins
    expect(a.reps).toBe(3); // independent field preserved
  });

  it('patchSet can clear effort with explicit null', () => {
    const sid = 's1';
    const ops: SyncOp[] = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1', effort_rir: 2 })),
      { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { effort_rir: null } },
    ];
    const snap = applyOps(undefined, ops, sid)!;
    expect(snap.sets.find((s) => s.id === 'a')!.effort_rir).toBeNull();
  });

  it('deleteSet removes the set and compacts order_index', () => {
    const sid = 's1';
    const ops: SyncOp[] = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1' })),
      addSetOp(sid, makeSet({ id: 'b', exercise_id: 'ex1' })),
      addSetOp(sid, makeSet({ id: 'c', exercise_id: 'ex1' })),
      { opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: 'b' },
    ];
    const snap = applyOps(undefined, ops, sid)!;
    expect(snap.sets.map((s) => s.id)).toEqual(['a', 'c']);
    expect(snap.sets.map((s) => s.order_index)).toEqual([0, 1]);
  });

  it('reorderSets rewrites order to match the given id list', () => {
    const sid = 's1';
    const ops: SyncOp[] = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1' })),
      addSetOp(sid, makeSet({ id: 'b', exercise_id: 'ex1' })),
      addSetOp(sid, makeSet({ id: 'c', exercise_id: 'ex1' })),
      { opId: newOpId(), kind: 'reorderSets', sessionId: sid, payload: { set_ids: ['c', 'a', 'b'] } },
    ];
    const snap = applyOps(undefined, ops, sid)!;
    expect(snap.sets.map((s) => s.id)).toEqual(['c', 'a', 'b']);
    expect(snap.sets.map((s) => s.order_index)).toEqual([0, 1, 2]);
  });

  it('finishSession clears is_active and stamps ended_at', () => {
    const sid = 's1';
    const ops: SyncOp[] = [
      startOp(sid),
      { opId: newOpId(), kind: 'finishSession', sessionId: sid, payload: { ended_at: '2026-06-13T11:00:00Z' } },
    ];
    const snap = applyOps(undefined, ops, sid)!;
    expect(snap.is_active).toBe(false);
    expect(snap.ended_at).toBe('2026-06-13T11:00:00Z');
  });

  it('deleteSession yields null (the session is gone)', () => {
    const sid = 's1';
    const ops: SyncOp[] = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1' })),
      { opId: newOpId(), kind: 'deleteSession', sessionId: sid },
    ];
    expect(applyOps(undefined, ops, sid)).toBeNull();
  });

  it('total_volume_kg counts only normal sets', () => {
    const sid = 's1';
    const ops = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1', weight_kg: 100, reps: 5, set_type: 'normal' })),
      addSetOp(sid, makeSet({ id: 'b', exercise_id: 'ex1', weight_kg: 60, reps: 10, set_type: 'warmup' })),
      addSetOp(sid, makeSet({ id: 'c', exercise_id: 'ex1', weight_kg: 50, reps: 12, set_type: 'drop' })),
    ];
    const snap = applyOps(undefined, ops, sid)!;
    expect(snap.total_volume_kg).toBe(500); // only the normal set: 100*5
  });

  it('replaying onto a non-empty server base layers the local ops on top', () => {
    const sid = 's1';
    // The server already knows about set 'a'; locally we add 'b' and bump a's weight.
    const base: SessionSnapshot = {
      ...emptySnapshot(sid),
      sets: [makeSet({ id: 'a', exercise_id: 'ex1', order_index: 0, weight_kg: 100 })],
      set_count: 1,
      total_volume_kg: 500,
    };
    const ops: SyncOp[] = [
      { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { weight_kg: 105 } },
      addSetOp(sid, makeSet({ id: 'b', exercise_id: 'ex1', weight_kg: 110, reps: 5 })),
    ];
    const snap = applyOps(base, ops, sid)!;
    expect(snap.sets.map((s) => s.id)).toEqual(['a', 'b']);
    expect(snap.sets.find((s) => s.id === 'a')!.weight_kg).toBe(105);
    expect(snap.sets.find((s) => s.id === 'b')!.order_index).toBe(1);
  });

  it('a patch/delete that targets an unknown set is a harmless no-op', () => {
    const sid = 's1';
    const ops: SyncOp[] = [
      startOp(sid),
      { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'ghost', payload: { reps: 9 } },
      { opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: 'ghost' },
    ];
    const snap = applyOps(undefined, ops, sid)!;
    expect(snap.sets).toEqual([]);
  });

  it('is a pure function — replaying the same ops twice gives the same snapshot', () => {
    const sid = 's1';
    const ops = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1' })),
      { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { reps: 8 } } as SyncOp,
    ];
    const first = applyOps(undefined, ops, sid);
    const second = applyOps(undefined, ops, sid);
    expect(second).toEqual(first);
  });
});

describe('compactSetOrder', () => {
  it('makes order_index 0-based and gap-free, preserving relative order', () => {
    const sets = [
      makeSet({ id: 'a', exercise_id: 'ex1', order_index: 5 }),
      makeSet({ id: 'b', exercise_id: 'ex1', order_index: 2 }),
      makeSet({ id: 'c', exercise_id: 'ex1', order_index: 9 }),
    ];
    const out = compactSetOrder(sets);
    expect(out.map((s) => s.id)).toEqual(['b', 'a', 'c']); // sorted by current order
    expect(out.map((s) => s.order_index)).toEqual([0, 1, 2]);
  });
});

describe('collapseQueue — drop ops that cancel out (the LWW / no-churn rule)', () => {
  it('a set created then deleted while still local removes ALL its ops', () => {
    const sid = 's1';
    const create = addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1' }));
    const patch: SyncOp = { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { reps: 8 } };
    const del: SyncOp = { opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: 'a' };
    const q = [startOp(sid), create, patch, del];
    const collapsed = collapseQueue(q);
    // The create/patch/delete trio for the never-synced set 'a' all vanish;
    // only the start op remains.
    expect(collapsed.map((o) => o.kind)).toEqual(['startSession']);
  });

  it('keeps the delete when the set was NOT created in the queue (server-known set)', () => {
    const sid = 's1';
    // No addSet for 'a' in the queue → 'a' lives on the server, so its delete
    // is a real mutation that must replay.
    const del: SyncOp = { opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: 'a' };
    const q = [del];
    expect(collapseQueue(q)).toEqual(q);
  });

  it('folds multiple patches to a still-local created set into the create payload', () => {
    const sid = 's1';
    const create = addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1', weight_kg: 100, reps: 5 }));
    const p1: SyncOp = { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { weight_kg: 110 } };
    const p2: SyncOp = { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { reps: 3 } };
    const collapsed = collapseQueue([create, p1, p2]);
    // One addSet remains, carrying the final values; the patches are folded in.
    expect(collapsed).toHaveLength(1);
    const only = collapsed[0];
    expect(only.kind).toBe('addSet');
    if (only.kind !== 'addSet') throw new Error('expected addSet');
    expect(only.payload.weight_kg).toBe(110);
    expect(only.payload.reps).toBe(3);
  });

  it('dropping a whole local session removes every op for it', () => {
    const sid = 's1';
    const q = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1' })),
      { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { reps: 8 } } as SyncOp,
      { opId: newOpId(), kind: 'deleteSession', sessionId: sid } as SyncOp,
    ];
    expect(collapseQueue(q)).toEqual([]);
  });

  it('keeps deleteSession when the session was server-created (no startSession queued)', () => {
    const sid = 's1';
    const del: SyncOp = { opId: newOpId(), kind: 'deleteSession', sessionId: sid };
    expect(collapseQueue([del])).toEqual([del]);
  });

  it('does not collapse across different sessions', () => {
    const create1 = addSetOp('s1', makeSet({ id: 'a', exercise_id: 'ex1' }));
    const del2: SyncOp = { opId: newOpId(), kind: 'deleteSet', sessionId: 's2', setId: 'a' };
    const q = [create1, del2];
    // Same set id string but different sessions → independent; nothing cancels.
    expect(collapseQueue(q)).toEqual(q);
  });

  it('replaying a collapsed queue yields the SAME snapshot as the raw queue', () => {
    const sid = 's1';
    const q: SyncOp[] = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1', weight_kg: 100, reps: 5 })),
      addSetOp(sid, makeSet({ id: 'b', exercise_id: 'ex1', weight_kg: 80, reps: 8 })),
      { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'b', payload: { weight_kg: 85 } },
      { opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: 'a' },
    ];
    const raw = applyOps(undefined, q, sid);
    const collapsed = applyOps(undefined, collapseQueue(q), sid);
    expect(collapsed).toEqual(raw);
  });

  // --- reorderSets × collapse (regression: a reorder naming a dropped set must
  // not survive collapse still referencing that phantom id, or the server
  // reorder 400s and the engine drops it — losing the reorder entirely). ---

  it('prunes a dropped set out of a reorderSets payload (created-then-deleted offline)', () => {
    const sid = 's1';
    // Offline: add b, reorder [b, a], then delete b — b never reaches the server.
    const q: SyncOp[] = [
      addSetOp(sid, makeSet({ id: 'b', exercise_id: 'ex1' })),
      { opId: newOpId(), kind: 'reorderSets', sessionId: sid, payload: { set_ids: ['b', 'a'] } },
      { opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: 'b' },
    ];
    const collapsed = collapseQueue(q);
    // b's add+delete vanish; the surviving reorder no longer names the phantom b.
    expect(collapsed.map((o) => o.kind)).toEqual(['reorderSets']);
    const reorder = collapsed[0];
    if (reorder.kind !== 'reorderSets') throw new Error('expected reorderSets');
    expect(reorder.payload.set_ids).toEqual(['a']);
  });

  it('drops a reorderSets op entirely when collapse empties its set_ids', () => {
    const sid = 's1';
    // Both reordered sets are created-then-deleted locally → the reorder is moot.
    const q: SyncOp[] = [
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1' })),
      addSetOp(sid, makeSet({ id: 'b', exercise_id: 'ex1' })),
      { opId: newOpId(), kind: 'reorderSets', sessionId: sid, payload: { set_ids: ['b', 'a'] } },
      { opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: 'a' },
      { opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: 'b' },
    ];
    expect(collapseQueue(q)).toEqual([]);
  });

  it('keeps reorderSets ids that are NOT dropped (mix of server-known + surviving local)', () => {
    const sid = 's1';
    const q: SyncOp[] = [
      addSetOp(sid, makeSet({ id: 'c', exercise_id: 'ex1' })), // surviving local create
      { opId: newOpId(), kind: 'reorderSets', sessionId: sid, payload: { set_ids: ['c', 'a', 'b'] } },
    ];
    // a + b are server-known (no local create); c survives → all three kept, order intact.
    const collapsed = collapseQueue(q);
    const reorder = collapsed.find((o) => o.kind === 'reorderSets');
    if (!reorder || reorder.kind !== 'reorderSets') throw new Error('expected reorderSets');
    expect(reorder.payload.set_ids).toEqual(['c', 'a', 'b']);
  });

  it('reorderSets pruning is replay-invariant (collapsed snapshot == raw snapshot)', () => {
    const sid = 's1';
    const q: SyncOp[] = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1' })),
      addSetOp(sid, makeSet({ id: 'b', exercise_id: 'ex1' })),
      { opId: newOpId(), kind: 'reorderSets', sessionId: sid, payload: { set_ids: ['b', 'a'] } },
      { opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: 'b' },
    ];
    const raw = applyOps(undefined, q, sid);
    const collapsed = applyOps(undefined, collapseQueue(q), sid);
    expect(collapsed).toEqual(raw);
  });
});

describe('reconcileServerSession — merge authoritative server state with pending local ops', () => {
  it('with no pending ops, the server snapshot wins outright', () => {
    const sid = 's1';
    const server: SessionDetail = {
      ...emptySnapshot(sid),
      sets: [makeSet({ id: 'a', exercise_id: 'ex1', order_index: 0, weight_kg: 100 })],
      set_count: 1,
      total_volume_kg: 500,
    };
    const merged = reconcileServerSession(server, []);
    expect(merged.sets.map((s) => s.id)).toEqual(['a']);
    expect(merged.sets[0].weight_kg).toBe(100);
  });

  it('re-applies still-pending local ops on top of the fresh server snapshot (LWW)', () => {
    const sid = 's1';
    // The server has set 'a' at 100kg; a local patch to 110 has NOT synced yet.
    const server: SessionDetail = {
      ...emptySnapshot(sid),
      sets: [makeSet({ id: 'a', exercise_id: 'ex1', order_index: 0, weight_kg: 100 })],
      set_count: 1,
      total_volume_kg: 500,
    };
    const pending: SyncOp[] = [
      { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { weight_kg: 110 } },
    ];
    const merged = reconcileServerSession(server, pending);
    // Local pending write wins until it syncs.
    expect(merged.sets.find((s) => s.id === 'a')!.weight_kg).toBe(110);
  });

  it('only re-applies pending ops for the reconciled session', () => {
    const sid = 's1';
    const server: SessionDetail = {
      ...emptySnapshot(sid),
      sets: [makeSet({ id: 'a', exercise_id: 'ex1', order_index: 0 })],
      set_count: 1,
    };
    const pending: SyncOp[] = [
      addSetOp('OTHER', makeSet({ id: 'z', exercise_id: 'ex9' })),
      addSetOp(sid, makeSet({ id: 'b', exercise_id: 'ex1' })),
    ];
    const merged = reconcileServerSession(server, pending);
    expect(merged.sets.map((s) => s.id)).toEqual(['a', 'b']);
  });
});

describe('serialize / deserialize — rehydration (kill mid-session loses nothing)', () => {
  it('round-trips the queue exactly', () => {
    const sid = 's1';
    const q: SyncOp[] = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1' })),
      { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { reps: 8 } },
    ];
    const restored = deserializeQueue(serializeQueue(q));
    expect(restored).toEqual(q);
  });

  it('a snapshot rebuilt from the rehydrated queue matches the live one', () => {
    const sid = 's1';
    const q: SyncOp[] = [
      startOp(sid),
      addSetOp(sid, makeSet({ id: 'a', exercise_id: 'ex1', weight_kg: 100, reps: 5 })),
      { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: 'a', payload: { weight_kg: 110 } },
    ];
    const live = applyOps(undefined, q, sid);
    const rehydrated = applyOps(undefined, deserializeQueue(serializeQueue(q)), sid);
    expect(rehydrated).toEqual(live);
  });
});

describe('integration: an offline gym session replays correctly on reconnect', () => {
  it('start → log 3 sets → edit → delete → finish, then drain to the server in order', () => {
    const sid = id('sess');
    const ex = id('ex');
    const s1 = id('set');
    const s2 = id('set');
    const s3 = id('set');

    // Everything is captured offline, FIFO.
    let q: SyncOp[] = [];
    q = enqueue(q, startOp(sid));
    q = enqueue(q, addSetOp(sid, makeSet({ id: s1, exercise_id: ex, weight_kg: 100, reps: 5 })));
    q = enqueue(q, addSetOp(sid, makeSet({ id: s2, exercise_id: ex, weight_kg: 100, reps: 5 })));
    q = enqueue(q, addSetOp(sid, makeSet({ id: s3, exercise_id: ex, weight_kg: 100, reps: 5 })));
    q = enqueue(q, { opId: newOpId(), kind: 'patchSet', sessionId: sid, setId: s2, payload: { reps: 6 } });
    q = enqueue(q, { opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: s3 });
    q = enqueue(q, { opId: newOpId(), kind: 'finishSession', sessionId: sid, payload: { ended_at: '2026-06-13T11:00:00Z' } });

    // The optimistic UI view while offline:
    const optimistic = applyOps(undefined, q, sid)!;
    expect(optimistic.sets.map((s) => s.id)).toEqual([s1, s2]);
    expect(optimistic.sets.find((s) => s.id === s2)!.reps).toBe(6);
    expect(optimistic.is_active).toBe(false);

    // Drain order is exactly FIFO (the network layer walks this list).
    const collapsed = collapseQueue(q);
    expect(collapsed.map((o) => o.kind)).toEqual([
      'startSession',
      'addSet', // s1
      'addSet', // s2 (with reps folded to 6)
      'finishSession',
    ]);
    // s3's add+delete cancelled; s2's patch folded into its add.
    const s2create = collapsed.find(
      (o): o is Extract<SyncOp, { kind: 'addSet' }> =>
        o.kind === 'addSet' && o.payload.id === s2,
    )!;
    expect(s2create.payload.reps).toBe(6);

    // After the server applies the collapsed queue, the authoritative snapshot
    // (here simulated) reconciles with zero pending ops → matches optimistic.
    const serverFinal: SessionDetail = {
      ...optimistic,
    };
    const reconciled = reconcileServerSession(serverFinal, []);
    expect(reconciled.sets.map((s) => s.id)).toEqual([s1, s2]);
    expect(reconciled.is_active).toBe(false);
  });
});
