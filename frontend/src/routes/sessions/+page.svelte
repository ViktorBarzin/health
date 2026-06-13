<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import type { SessionDetail, SessionSummary } from '$lib/types';
  import { formatDate, formatNumber, formatTime } from '$lib/utils/format';

  // The user's logged Sessions, newest first. "Train" is the core action: the
  // big button starts a fresh Session and drops the user straight into logging.
  let sessions = $state<SessionSummary[]>([]);
  let loading = $state(true);
  let error = $state('');
  let starting = $state(false);

  $effect(() => {
    load();
  });

  async function load() {
    loading = true;
    error = '';
    try {
      sessions = await api.get<SessionSummary[]>('/api/sessions/');
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load sessions';
    } finally {
      loading = false;
    }
  }

  async function startSession() {
    if (starting) return;
    starting = true;
    error = '';
    try {
      const created = await api.post<SessionDetail>('/api/sessions/', {});
      await goto(`/sessions/${created.id}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to start session';
      starting = false;
    }
  }

  // The single active (unfinished) Session, if any — resuming it beats starting
  // a second one.
  let activeSession = $derived(sessions.find((s) => s.is_active));

  function durationLabel(s: SessionSummary): string {
    const start = new Date(s.started_at).getTime();
    const end = s.ended_at ? new Date(s.ended_at).getTime() : Date.now();
    const mins = Math.max(0, Math.round((end - start) / 60000));
    if (mins < 60) return `${mins}m`;
    return `${Math.floor(mins / 60)}h ${mins % 60}m`;
  }
</script>

<div class="space-y-4 pb-24">
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-semibold text-surface-100">Train</h1>
  </div>

  <!-- Resume active or start a new Session -->
  {#if activeSession}
    <a
      href="/sessions/{activeSession.id}"
      class="flex items-center justify-between gap-3 w-full p-4 rounded-2xl
             bg-primary-500/15 border border-primary-500/40 hover:bg-primary-500/25 transition-colors"
    >
      <div class="flex items-center gap-3">
        <span class="relative flex h-3 w-3">
          <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary-400 opacity-75"></span>
          <span class="relative inline-flex rounded-full h-3 w-3 bg-primary-500"></span>
        </span>
        <div>
          <p class="text-sm font-semibold text-primary-200">Session in progress</p>
          <p class="text-xs text-primary-300/80">
            {activeSession.set_count} set{activeSession.set_count !== 1 ? 's' : ''} · {durationLabel(activeSession)}
          </p>
        </div>
      </div>
      <svg class="w-5 h-5 text-primary-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
      </svg>
    </a>
  {:else}
    <button
      onclick={startSession}
      disabled={starting}
      class="flex items-center justify-center gap-2 w-full py-4 rounded-2xl
             bg-primary-500 hover:bg-primary-600 text-white font-semibold text-base
             transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-primary-500/20"
    >
      {#if starting}
        <div class="w-5 h-5 border-2 border-white/50 border-t-transparent rounded-full animate-spin"></div>
        Starting…
      {:else}
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
        Start session
      {/if}
    </button>
  {/if}

  {#if error}
    <p class="text-sm text-red-400">{error}</p>
  {/if}

  <!-- History -->
  {#if loading}
    <div class="space-y-2">
      {#each Array(4) as _}
        <div class="h-20 bg-surface-800 rounded-xl border border-surface-700 animate-pulse"></div>
      {/each}
    </div>
  {:else if sessions.length === 0}
    <div class="p-12 text-center bg-surface-800 rounded-xl border border-surface-700">
      <svg class="w-12 h-12 text-surface-600 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 6.75v10.5m10.5-10.5v10.5M4.5 9.75h2.25m10.5 0H19.5M4.5 14.25h2.25m10.5 0H19.5M6.75 12h10.5" />
      </svg>
      <p class="text-surface-400 text-sm">No sessions yet. Start your first one above.</p>
    </div>
  {:else}
    <div class="space-y-2">
      {#each sessions as s (s.id)}
        <a
          href="/sessions/{s.id}"
          class="block p-4 rounded-xl bg-surface-800 border border-surface-700
                 hover:border-surface-600 hover:bg-surface-800/80 transition-all"
        >
          <div class="flex items-center justify-between gap-3">
            <div class="min-w-0">
              <p class="text-sm font-medium text-surface-200">
                {formatDate(s.started_at)}
                <span class="text-surface-500 font-normal">· {formatTime(s.started_at)}</span>
              </p>
              <p class="mt-0.5 text-xs text-surface-500">
                {s.set_count} set{s.set_count !== 1 ? 's' : ''}
                · {durationLabel(s)}
                {#if s.total_volume_kg > 0}
                  · {formatNumber(s.total_volume_kg)} kg volume
                {/if}
              </p>
            </div>
            {#if s.is_active}
              <span class="shrink-0 text-[0.6rem] font-semibold uppercase tracking-wide px-2 py-0.5 rounded-full
                           bg-primary-500/20 text-primary-300">Active</span>
            {/if}
          </div>
        </a>
      {/each}
    </div>
  {/if}
</div>
