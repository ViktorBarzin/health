import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// The sync ENGINE orchestration: FIFO drain, stop-on-transient, drop-on-
// permanent-4xx, idempotent replay. We mock the HTTP client and run in node
// (no IndexedDB → store.ts no-ops, the engine runs purely in-memory), so this
// exercises the real drain logic without a browser or new deps. The pure
// queue/replay logic has its own exhaustive suite (queue.test.ts).

// --- Mock the API client so no real network happens. ---
const calls: { method: string; path: string; body?: unknown }[] = [];
let failer: ((path: string, method: string) => void) | null = null;

vi.mock('$lib/api', async () => {
  // Re-export a real-shaped ApiError so `instanceof` checks in the engine work.
  class ApiError extends Error {
    status: number;
    body: unknown;
    constructor(status: number, body: unknown) {
      super(`API error ${status}`);
      this.name = 'ApiError';
      this.status = status;
      this.body = body;
    }
  }
  const record = (method: string) => (path: string, body?: unknown) => {
    calls.push({ method, path, body });
    if (failer) failer(path, method);
    return Promise.resolve(undefined);
  };
  return {
    ApiError,
    api: {
      get: record('GET'),
      post: record('POST'),
      put: record('PUT'),
      patch: record('PATCH'),
      delete: record('DELETE'),
    },
  };
});

// The reactive sync-state uses Svelte runes ($state), which aren't available
// in the plain `node` test env — stub it with a inert plain object (the engine
// only calls setters + reads `errored`).
vi.mock('./sync-state.svelte', () => {
  const s = {
    online: true,
    pending: 0,
    syncing: false,
    errored: false,
    setOnline(v: boolean) {
      s.online = v;
    },
    setPending(n: number) {
      s.pending = n;
    },
    setSyncing(v: boolean) {
      s.syncing = v;
    },
    setErrored(v: boolean) {
      s.errored = v;
    },
  };
  return { syncState: s };
});

// Import AFTER the mocks are registered.
import { ApiError } from '$lib/api';
import { drain, enqueueOp, queueLength } from './engine';
import { newOpId, type SyncOp } from './queue';
import type { TrainingSet } from '$lib/types';

function setOnline(v: boolean) {
  Object.defineProperty(globalThis, 'navigator', {
    value: { onLine: v },
    configurable: true,
  });
}

function startOp(sessionId: string): SyncOp {
  return { opId: newOpId(), kind: 'startSession', sessionId, payload: { started_at: '2026-06-13T10:00:00Z' } };
}

function addSetOp(sessionId: string, id: string): SyncOp {
  const set: TrainingSet = {
    id,
    exercise_id: 'ex1',
    order_index: 0,
    weight_kg: 100,
    reps: 5,
    set_type: 'normal',
    effort_rir: null,
    superset_group: null,
    exercise_name: null,
  };
  return { opId: newOpId(), kind: 'addSet', sessionId, payload: set };
}

// Enqueue a batch WHILE OFFLINE so no drain fires mid-enqueue (deterministic):
// the engine only drains when online, so this just stages the queue.
async function stage(ops: SyncOp[]): Promise<void> {
  setOnline(false);
  for (const op of ops) await enqueueOp(op);
  setOnline(true);
}

beforeEach(async () => {
  // Ensure a clean shared queue: drain whatever a prior test left, online and
  // succeeding, before each test (module state is file-scoped).
  failer = null;
  setOnline(true);
  await drain();
  calls.length = 0;
});

describe('engine drain orchestration', () => {
  it('drains staged ops to the API in FIFO order, then empties', async () => {
    const sid = `s-${newOpId()}`;
    await stage([
      startOp(sid),
      addSetOp(sid, `set-a-${newOpId()}`),
      addSetOp(sid, `set-b-${newOpId()}`),
    ]);
    await drain();

    const paths = calls.map((c) => `${c.method} ${c.path}`);
    expect(paths[0]).toBe('POST /api/sessions/'); // start first
    expect(paths.filter((p) => p.endsWith('/sets'))).toHaveLength(2); // both sets
    expect(queueLength()).toBe(0); // fully drained
  });

  it('a startSession op posts the client-supplied id', async () => {
    const sid = `s-${newOpId()}`;
    await stage([startOp(sid)]);
    await drain();
    const start = calls.find((c) => c.path === '/api/sessions/')!;
    expect((start.body as { id: string }).id).toBe(sid);
  });

  it('stops at the first TRANSIENT failure and keeps the tail for retry', async () => {
    const sid = `s-${newOpId()}`;
    await stage([startOp(sid), addSetOp(sid, `set-x-${newOpId()}`)]);

    // Fail the set add with a network-ish error (not an ApiError → transient).
    failer = (path) => {
      if (path.endsWith('/sets')) throw new Error('network down');
    };
    await drain();

    // The start delivered; the failing set stays queued (order preserved).
    expect(queueLength()).toBe(1);

    // Recover: clear the failer and drain again → the set goes through.
    failer = null;
    await drain();
    expect(queueLength()).toBe(0);
  });

  it('drops a PERMANENT 4xx op so it cannot wedge the queue forever', async () => {
    const sid = `s-${newOpId()}`;
    await stage([
      startOp(sid),
      addSetOp(sid, `set-bad-${newOpId()}`),
      addSetOp(sid, `set-ok-${newOpId()}`),
    ]);

    // The FIRST set add 422s (unprocessable — re-sending won't help → drop it);
    // the start and the second set succeed.
    let firstSet = true;
    failer = (path) => {
      if (path.endsWith('/sets') && firstSet) {
        firstSet = false;
        throw new ApiError(422, { detail: 'bad' });
      }
    };
    await drain();

    // Queue empties: bad op dropped, others delivered.
    expect(queueLength()).toBe(0);
    // The good set was still attempted (we didn't stop on the permanent error).
    const setCalls = calls.filter((c) => c.path.endsWith('/sets'));
    expect(setCalls.length).toBe(2);
  });

  it('does not drain while offline; resumes when back online', async () => {
    const sid = `s-${newOpId()}`;
    setOnline(false);
    await enqueueOp(startOp(sid));
    await drain();
    expect(queueLength()).toBe(1); // nothing sent offline
    expect(calls.length).toBe(0);

    setOnline(true);
    await drain();
    expect(queueLength()).toBe(0); // drains on reconnect
  });

  it('treats a 404 on delete as already-done (drops it)', async () => {
    const sid = `s-${newOpId()}`;
    await stage([{ opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: 'gone' }]);
    failer = (path, method) => {
      if (method === 'DELETE') throw new ApiError(404, { detail: 'not found' });
    };
    await drain();
    // 404-on-delete == success: the op is dropped, queue empties.
    expect(queueLength()).toBe(0);
  });

  it('drops a PERMANENT 400 reorder rather than wedging the queue', async () => {
    // Pins the engine's drop-on-permanent for a reorder specifically: even if a
    // stale set_ids slips through to a strict server, a 400 must not wedge.
    const sid = `s-${newOpId()}`;
    await stage([
      { opId: newOpId(), kind: 'reorderSets', sessionId: sid, payload: { set_ids: ['x', 'y'] } },
      addSetOp(sid, `after-${newOpId()}`),
    ]);
    failer = (path, method) => {
      if (method === 'PUT' && path.endsWith('/sets/order')) {
        throw new ApiError(400, { detail: 'not a permutation' });
      }
    };
    await drain();
    // Reorder dropped (permanent 4xx), the following add still delivered.
    expect(queueLength()).toBe(0);
    expect(calls.some((c) => c.path.endsWith('/sets'))).toBe(true);
  });

  it('re-derives a reorder set_ids at SEND time, stripping a set deleted earlier in the queue', async () => {
    // Repro #2: server-known {a, b}; offline the user deletes a, THEN reorders
    // to [b, a]. FIFO drains delete(a) first → the reorder must go out as [b]
    // (a is gone), not the stale [b, a] that a strict server would reject.
    const sid = `s-${newOpId()}`;
    await stage([
      { opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: 'a' },
      { opId: newOpId(), kind: 'reorderSets', sessionId: sid, payload: { set_ids: ['b', 'a'] } },
    ]);
    await drain();

    const reorder = calls.find((c) => c.path.endsWith('/sets/order'))!;
    expect(reorder).toBeTruthy();
    expect((reorder.body as { set_ids: string[] }).set_ids).toEqual(['b']);
    expect(queueLength()).toBe(0);
  });

  it('leaves a reorder set_ids intact when its delete comes AFTER it (order-aware)', async () => {
    // The mirror case: reorder [b, a] is queued BEFORE delete(b). At reorder
    // send time b still exists server-side, so the reorder goes out as-is; the
    // later delete removes b. Stripping b here would be wrong.
    const sid = `s-${newOpId()}`;
    await stage([
      { opId: newOpId(), kind: 'reorderSets', sessionId: sid, payload: { set_ids: ['b', 'a'] } },
      { opId: newOpId(), kind: 'deleteSet', sessionId: sid, setId: 'b' },
    ]);
    await drain();

    const reorder = calls.find((c) => c.path.endsWith('/sets/order'))!;
    expect((reorder.body as { set_ids: string[] }).set_ids).toEqual(['b', 'a']);
  });
});
