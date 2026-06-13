/**
 * Offline-first Session LIST + start-a-Session (ADR-0005, #6).
 *
 * The `/sessions` (Train) page binds to this. It merges the server's Session
 * list with any Sessions born offline (cached snapshots not yet synced), and
 * lets the user start a new Session with zero signal — the Session id is minted
 * locally and a `startSession` op is queued, so the user drops straight into
 * logging even in a dead zone.
 */

import { api } from '$lib/api';
import type { SessionSummary } from '$lib/types';
import { enqueueOp } from './engine';
import { newOpId, type SessionSnapshot } from './queue';
import { getAllSnapshots, putSnapshot } from './store';
import { newId } from './session-store.svelte';

function summaryFromSnapshot(s: SessionSnapshot): SessionSummary {
  return {
    id: s.id,
    started_at: s.started_at,
    ended_at: s.ended_at,
    is_active: s.ended_at === null,
    set_count: s.set_count,
    total_volume_kg: s.total_volume_kg,
  };
}

/** Merge server + cached-offline sessions, newest first, de-duped by id. */
function mergeSessions(
  server: SessionSummary[],
  cached: SessionSnapshot[],
): SessionSummary[] {
  const byId = new Map<string, SessionSummary>();
  // Cached (possibly-offline) first, server overwrites with authoritative data.
  for (const s of cached) byId.set(s.id, summaryFromSnapshot(s));
  for (const s of server) byId.set(s.id, s);
  return [...byId.values()].sort(
    (a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime(),
  );
}

export function createSessionsList() {
  let sessions = $state<SessionSummary[]>([]);
  let loading = $state(true);
  let error = $state('');

  async function load() {
    loading = true;
    error = '';
    let cached: SessionSnapshot[] = [];
    try {
      cached = await getAllSnapshots();
    } catch {
      cached = [];
    }
    try {
      const server = await api.get<SessionSummary[]>('/api/sessions/');
      sessions = mergeSessions(server, cached);
    } catch (err) {
      // Offline (or API down): show whatever we cached locally.
      if (cached.length > 0) {
        sessions = mergeSessions([], cached);
      } else {
        error = err instanceof Error ? err.message : 'Failed to load sessions';
      }
    } finally {
      loading = false;
    }
  }

  return {
    get sessions() {
      return sessions;
    },
    get loading() {
      return loading;
    },
    get error() {
      return error;
    },
    load,
  };
}

/**
 * Start a new Session — works offline. Mints the id locally, caches an empty
 * active snapshot, and queues the `startSession` op. Returns the id so the
 * caller can navigate straight to `/sessions/{id}`.
 */
export async function startSessionOffline(): Promise<string> {
  const id = newId();
  const startedAt = new Date().toISOString();
  const snapshot: SessionSnapshot = {
    id,
    started_at: startedAt,
    ended_at: null,
    is_active: true,
    set_count: 0,
    total_volume_kg: 0,
    sets: [],
  };
  await putSnapshot(snapshot);
  await enqueueOp({
    opId: newOpId(),
    kind: 'startSession',
    sessionId: id,
    payload: { started_at: startedAt },
  });
  return id;
}
