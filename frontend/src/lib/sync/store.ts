/**
 * IndexedDB persistence for the offline Session-logging queue (ADR-0005, #6).
 *
 * This is the IO half of the sync layer; the pure data logic lives in
 * `queue.ts` (and is unit-tested without a browser). Here we durably store:
 *
 *   - `ops`: the FIFO log of pending {@link SyncOp}s, one row per op keyed by
 *     `opId`, ordered by a monotonic `seq`. Durable so killing/reloading the
 *     app mid-Session loses nothing — every logged Set survives as its enqueued
 *     op and replays on next launch.
 *   - `snapshots`: the last authoritative server {@link SessionSnapshot} per
 *     Session id, so the optimistic view rebuilds offline with zero signal
 *     (replay the pending ops over the cached snapshot).
 *   - `kv`: small key/value bag for prefetched context (exercise names, the
 *     active Recommendation/targets the logging screen needs offline).
 *
 * Uses `idb` (a thin, well-maintained IndexedDB Promise wrapper already in the
 * dependency tree). All access is guarded for SSR / no-IndexedDB environments
 * so importing this module never throws on the server.
 */

import { type DBSchema, type IDBPDatabase, openDB } from 'idb';
import type { SessionSnapshot, SyncOp } from './queue';

const DB_NAME = 'health-offline';
const DB_VERSION = 1;

/** A stored op row: the op plus a monotonic sequence for stable FIFO order. */
export interface StoredOp {
  opId: string;
  seq: number;
  op: SyncOp;
}

interface OfflineDB extends DBSchema {
  ops: {
    key: string; // opId
    value: StoredOp;
    indexes: { seq: number };
  };
  snapshots: {
    key: string; // session id
    value: SessionSnapshot;
  };
  kv: {
    key: string;
    value: unknown;
  };
}

function hasIndexedDB(): boolean {
  return typeof indexedDB !== 'undefined';
}

let dbPromise: Promise<IDBPDatabase<OfflineDB>> | null = null;

function getDB(): Promise<IDBPDatabase<OfflineDB>> {
  if (!hasIndexedDB()) {
    return Promise.reject(new Error('IndexedDB unavailable'));
  }
  if (!dbPromise) {
    dbPromise = openDB<OfflineDB>(DB_NAME, DB_VERSION, {
      upgrade(db) {
        const ops = db.createObjectStore('ops', { keyPath: 'opId' });
        ops.createIndex('seq', 'seq');
        db.createObjectStore('snapshots');
        db.createObjectStore('kv');
      },
    });
  }
  return dbPromise;
}

// A process-local monotonic sequence. Persisted ops also carry it; on load we
// continue past the highest stored value so order survives a reload.
let seqCounter = 0;
function nextSeq(): number {
  seqCounter += 1;
  return seqCounter;
}

// --------------------------------------------------------------------------- //
// Queue persistence
// --------------------------------------------------------------------------- //

/** Append an op to the durable queue (FIFO). No-op if IndexedDB is unavailable. */
export async function persistOp(op: SyncOp): Promise<void> {
  if (!hasIndexedDB()) return;
  const db = await getDB();
  await db.put('ops', { opId: op.opId, seq: nextSeq(), op });
}

/** Load all pending ops in FIFO (seq) order. */
export async function loadOps(): Promise<SyncOp[]> {
  if (!hasIndexedDB()) return [];
  const db = await getDB();
  const rows = await db.getAllFromIndex('ops', 'seq');
  // Keep the process counter ahead of anything we just loaded so subsequent
  // enqueues sort after the rehydrated ones.
  for (const r of rows) if (r.seq > seqCounter) seqCounter = r.seq;
  return rows.map((r) => r.op);
}

/** Remove an op from the queue once it has synced. */
export async function removeOp(opId: string): Promise<void> {
  if (!hasIndexedDB()) return;
  const db = await getDB();
  await db.delete('ops', opId);
}

/** Replace the entire queue (used after collapse). */
export async function replaceQueue(ops: SyncOp[]): Promise<void> {
  if (!hasIndexedDB()) return;
  const db = await getDB();
  const tx = db.transaction('ops', 'readwrite');
  await tx.store.clear();
  let s = 0;
  for (const op of ops) {
    s += 1;
    await tx.store.put({ opId: op.opId, seq: s, op });
  }
  await tx.done;
  seqCounter = s;
}

/** Count pending ops (for the sync-state indicator). */
export async function countOps(): Promise<number> {
  if (!hasIndexedDB()) return 0;
  const db = await getDB();
  return db.count('ops');
}

// --------------------------------------------------------------------------- //
// Snapshot persistence
// --------------------------------------------------------------------------- //

/** Store the last authoritative server snapshot for a Session. */
export async function putSnapshot(snapshot: SessionSnapshot): Promise<void> {
  if (!hasIndexedDB()) return;
  const db = await getDB();
  await db.put('snapshots', snapshot, snapshot.id);
}

/** Get the cached server snapshot for a Session, if any. */
export async function getSnapshot(sessionId: string): Promise<SessionSnapshot | undefined> {
  if (!hasIndexedDB()) return undefined;
  const db = await getDB();
  return db.get('snapshots', sessionId);
}

/** Get all cached snapshots (the offline Session list). */
export async function getAllSnapshots(): Promise<SessionSnapshot[]> {
  if (!hasIndexedDB()) return [];
  const db = await getDB();
  return db.getAll('snapshots');
}

/** Drop a cached snapshot (e.g. after a synced delete). */
export async function deleteSnapshot(sessionId: string): Promise<void> {
  if (!hasIndexedDB()) return;
  const db = await getDB();
  await db.delete('snapshots', sessionId);
}

// --------------------------------------------------------------------------- //
// KV (prefetched context)
// --------------------------------------------------------------------------- //

/** Store a small prefetched value (exercise names, today's targets, …). */
export async function putKV(key: string, value: unknown): Promise<void> {
  if (!hasIndexedDB()) return;
  const db = await getDB();
  await db.put('kv', value, key);
}

/** Read a prefetched value. */
export async function getKV<T>(key: string): Promise<T | undefined> {
  if (!hasIndexedDB()) return undefined;
  const db = await getDB();
  return (await db.get('kv', key)) as T | undefined;
}
