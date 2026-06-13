/**
 * Reactive sync-state the UI binds to (ADR-0005, #6) — the trust signal.
 *
 * A gym logger that silently drops Sets gets deleted, so the user must always
 * see where their data is: queued locally, syncing, or safely up. This is a
 * Svelte 5 runes store following the repo's factory pattern (see
 * `stores/auth.svelte.ts`): private `$state`, exposed via getters.
 *
 * `status` is derived from connectivity + the queue:
 *   - `offline`  — no connectivity; writes are being captured locally.
 *   - `syncing`  — online and actively draining the queue.
 *   - `pending`  — online with queued ops not yet drained (transient/visible
 *                  if a drain is scheduled or a previous one errored).
 *   - `error`    — the last drain attempt failed; will retry.
 *   - `synced`   — online and the queue is empty.
 */

export type SyncStatus = 'synced' | 'syncing' | 'pending' | 'offline' | 'error';

function createSyncState() {
  // Start optimistic-online during SSR (navigator is absent); the engine sets
  // the real value on the client.
  let online = $state(true);
  let pending = $state(0);
  let syncing = $state(false);
  let errored = $state(false);

  const status = $derived<SyncStatus>(
    !online
      ? 'offline'
      : syncing
        ? 'syncing'
        : errored && pending > 0
          ? 'error'
          : pending > 0
            ? 'pending'
            : 'synced',
  );

  /** Short, human label for the indicator. */
  const label = $derived.by(() => {
    switch (status) {
      case 'offline':
        return pending > 0
          ? `Offline — ${pending} change${pending === 1 ? '' : 's'} queued`
          : 'Offline';
      case 'syncing':
        return 'Syncing…';
      case 'pending':
        return `${pending} change${pending === 1 ? '' : 's'} to sync`;
      case 'error':
        return `Sync failed — ${pending} queued, will retry`;
      case 'synced':
        return 'Synced';
    }
  });

  return {
    get online() {
      return online;
    },
    get pending() {
      return pending;
    },
    get syncing() {
      return syncing;
    },
    get errored() {
      return errored;
    },
    get status() {
      return status;
    },
    get label() {
      return label;
    },
    setOnline(v: boolean) {
      online = v;
    },
    setPending(n: number) {
      pending = n;
    },
    setSyncing(v: boolean) {
      syncing = v;
      if (v) errored = false;
    },
    setErrored(v: boolean) {
      errored = v;
    },
  };
}

/** The app-wide sync-state singleton. */
export const syncState = createSyncState();
