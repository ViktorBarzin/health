<script lang="ts">
  import { syncState } from '$lib/sync/sync-state.svelte';
  import { syncNow } from '$lib/sync/session-store.svelte';

  // The trust signal (ADR-0005): a compact pill showing where the user's logged
  // Sets are — captured locally and queued (offline), draining (syncing),
  // waiting (pending), failed-but-will-retry (error), or safely up (synced).
  // Tapping it while there's anything outstanding forces a drain attempt.
  //
  // Mobile-first: small, unobtrusive, colour-coded; lives in the logging header.
  let status = $derived(syncState.status);
  let label = $derived(syncState.label);
  let actionable = $derived(syncState.pending > 0 || syncState.status === 'error');

  const dot: Record<string, string> = {
    synced: 'bg-emerald-400',
    syncing: 'bg-sky-400 animate-pulse',
    pending: 'bg-amber-400',
    offline: 'bg-surface-400',
    error: 'bg-red-400',
  };
  const text: Record<string, string> = {
    synced: 'text-emerald-300',
    syncing: 'text-sky-300',
    pending: 'text-amber-300',
    offline: 'text-surface-300',
    error: 'text-red-300',
  };
  const ring: Record<string, string> = {
    synced: 'border-emerald-500/30 bg-emerald-500/10',
    syncing: 'border-sky-500/30 bg-sky-500/10',
    pending: 'border-amber-500/30 bg-amber-500/10',
    offline: 'border-surface-600 bg-surface-700/40',
    error: 'border-red-500/30 bg-red-500/10',
  };
</script>

<button
  type="button"
  onclick={() => actionable && syncNow()}
  disabled={!actionable}
  class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[0.65rem] font-semibold
         transition-colors {ring[status]} {text[status]} {actionable
    ? 'cursor-pointer hover:brightness-125'
    : 'cursor-default'}"
  aria-live="polite"
  title={actionable ? 'Tap to sync now' : label}
>
  <span class="relative flex h-2 w-2">
    {#if status === 'syncing'}
      <span class="absolute inline-flex h-full w-full rounded-full {dot[status]} opacity-60"></span>
    {/if}
    <span class="relative inline-flex h-2 w-2 rounded-full {dot[status]}"></span>
  </span>
  <span class="whitespace-nowrap">{label}</span>
</button>
