<script lang="ts">
  import { api, ApiError } from '$lib/api';
  import {
    canSubmitToken,
    canSync,
    lastSyncSummary,
    statusLabel,
  } from '$lib/connections';
  import type {
    ConnectionProviderInfo,
    ConnectionSyncResult,
  } from '$lib/types';

  // Per-user Connections (BYOT integrations, ADR-0006): connect a data source
  // with your OWN token (e.g. an Oura Personal Access Token), pull on demand,
  // see status, disconnect. The token field is WRITE-ONLY — it is sent on
  // connect and never rendered back (the API never returns it).

  let providers = $state<ConnectionProviderInfo[]>([]);
  let loading = $state(true);
  let loadError = $state('');

  // Per-provider transient UI state, keyed by provider id.
  let tokenInput = $state<Record<string, string>>({});
  let showForm = $state<Record<string, boolean>>({});
  let busy = $state<Record<string, boolean>>({});
  let rowError = $state<Record<string, string>>({});
  let rowNotice = $state<Record<string, string>>({});

  $effect(() => {
    load();
  });

  async function load() {
    loading = true;
    loadError = '';
    try {
      providers = await api.get<ConnectionProviderInfo[]>('/api/connections');
    } catch (e) {
      loadError =
        e instanceof Error ? e.message : 'Could not load connections.';
      providers = [];
    } finally {
      loading = false;
    }
  }

  function toggleForm(p: string) {
    showForm[p] = !showForm[p];
    rowError[p] = '';
  }

  async function connect(provider: string) {
    const token = (tokenInput[provider] ?? '').trim();
    if (!canSubmitToken(token, busy[provider])) return;
    busy[provider] = true;
    rowError[provider] = '';
    rowNotice[provider] = '';
    try {
      await api.post('/api/connections', { provider, token });
      // Clear the token from memory immediately — never keep it around.
      tokenInput[provider] = '';
      showForm[provider] = false;
      rowNotice[provider] = 'Connected. Syncing your data…';
      await load();
      // Kick off a first sync so data lands without a second tap.
      await sync(provider);
    } catch (e) {
      rowError[provider] = errorMessage(e, 'Could not connect. Check your token.');
    } finally {
      busy[provider] = false;
    }
  }

  async function sync(provider: string) {
    busy[provider] = true;
    rowError[provider] = '';
    try {
      const result = await api.post<ConnectionSyncResult>(
        `/api/connections/${provider}/sync`,
      );
      if (result.status === 'error') {
        rowError[provider] =
          result.last_error ?? 'Sync failed — your token may be invalid.';
      } else {
        rowNotice[provider] =
          result.records_ingested > 0
            ? `Synced — ${result.records_ingested} new readings.`
            : 'Synced — already up to date.';
      }
      await load();
    } catch (e) {
      rowError[provider] = errorMessage(e, 'Sync failed. Please try again.');
    } finally {
      busy[provider] = false;
    }
  }

  async function disconnect(provider: string, label: string) {
    if (
      typeof window !== 'undefined' &&
      !window.confirm(`Disconnect ${label}? Your imported data is kept.`)
    ) {
      return;
    }
    busy[provider] = true;
    rowError[provider] = '';
    rowNotice[provider] = '';
    try {
      await api.delete(`/api/connections/${provider}`);
      await load();
    } catch (e) {
      rowError[provider] = errorMessage(e, 'Could not disconnect.');
    } finally {
      busy[provider] = false;
    }
  }

  function errorMessage(e: unknown, fallback: string): string {
    if (e instanceof ApiError && e.status === 503) {
      return 'Connections are unavailable — the server has no encryption key configured.';
    }
    return e instanceof Error ? e.message : fallback;
  }

  const toneClasses: Record<string, string> = {
    success: 'bg-green-500/15 text-green-400',
    error: 'bg-red-500/15 text-red-400',
    muted: 'bg-surface-600/40 text-surface-300',
    idle: 'bg-surface-600/40 text-surface-400',
  };
</script>

<div class="space-y-3">
  {#if loading}
    <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 animate-pulse">
      <div class="w-40 h-4 bg-surface-700 rounded"></div>
    </div>
  {:else if loadError}
    <div class="p-3 rounded-lg bg-red-500/10 border border-red-500/20">
      <p class="text-sm text-red-400">{loadError}</p>
    </div>
  {:else}
    {#each providers as p (p.provider)}
      {@const label = statusLabel(p)}
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-5 space-y-3">
        <!-- Header: name + status badge -->
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <h3 class="text-base font-semibold text-surface-100">{p.label}</h3>
            <p class="text-sm text-surface-400 mt-0.5">{p.description}</p>
          </div>
          <span
            class="shrink-0 px-2.5 py-1 rounded-full text-xs font-medium {toneClasses[label.tone]}"
          >
            {label.text}
          </span>
        </div>

        {#if p.connected}
          <!-- Connected: last-sync + actions -->
          <p class="text-xs text-surface-500">
            Last synced: {lastSyncSummary(p.last_sync_at)}
          </p>

          {#if p.status === 'error' && p.last_error}
            <div class="p-3 rounded-lg bg-red-500/10 border border-red-500/20">
              <p class="text-sm text-red-400">{p.last_error}</p>
              <p class="text-xs text-red-400/70 mt-1">
                Re-connect with a fresh token to fix this.
              </p>
            </div>
          {/if}

          <div class="flex flex-wrap gap-2">
            <button
              type="button"
              onclick={() => sync(p.provider)}
              disabled={!canSync(p, busy[p.provider])}
              class="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-500 hover:bg-primary-600 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {#if busy[p.provider]}
                <span class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" aria-hidden="true"></span>
                Syncing…
              {:else}
                Sync now
              {/if}
            </button>
            <button
              type="button"
              onclick={() => toggleForm(p.provider)}
              class="px-4 py-2 bg-surface-700 hover:bg-surface-600 text-surface-200 text-sm font-medium rounded-lg transition-colors"
            >
              Update token
            </button>
            <button
              type="button"
              onclick={() => disconnect(p.provider, p.label)}
              disabled={busy[p.provider]}
              class="px-4 py-2 text-red-400 hover:bg-red-500/10 disabled:opacity-50 text-sm font-medium rounded-lg transition-colors"
            >
              Disconnect
            </button>
          </div>
        {:else}
          <!-- Not connected: a Connect button that reveals the paste form -->
          {#if !showForm[p.provider]}
            <button
              type="button"
              onclick={() => toggleForm(p.provider)}
              class="inline-flex items-center justify-center px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium rounded-lg transition-colors"
            >
              Connect {p.label}
            </button>
          {/if}
        {/if}

        <!-- Paste-token form (connect or update). Token field is write-only. -->
        {#if showForm[p.provider]}
          <div class="pt-1 space-y-2">
            <label class="block text-sm text-surface-300" for="token-{p.provider}">
              Paste your {p.label} access token
            </label>
            <input
              id="token-{p.provider}"
              type="password"
              autocomplete="off"
              spellcheck="false"
              bind:value={tokenInput[p.provider]}
              placeholder="Personal Access Token"
              class="w-full px-3 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-sm text-surface-100 placeholder:text-surface-600 focus:outline-none focus:border-primary-500"
            />
            {#if p.instructions_url}
              <p class="text-xs text-surface-500">
                Get one at
                <a
                  href={p.instructions_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  class="text-primary-400 hover:underline"
                >
                  {p.instructions_url.replace(/^https?:\/\//, '')}
                </a>
              </p>
            {/if}
            <div class="flex gap-2 pt-1">
              <button
                type="button"
                onclick={() => connect(p.provider)}
                disabled={!canSubmitToken(tokenInput[p.provider] ?? '', busy[p.provider])}
                class="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-500 hover:bg-primary-600 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
              >
                {#if busy[p.provider]}
                  <span class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" aria-hidden="true"></span>
                  Connecting…
                {:else}
                  Save & sync
                {/if}
              </button>
              <button
                type="button"
                onclick={() => toggleForm(p.provider)}
                class="px-4 py-2 bg-surface-700 hover:bg-surface-600 text-surface-200 text-sm font-medium rounded-lg transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        {/if}

        {#if rowError[p.provider]}
          <p class="text-sm text-red-400">{rowError[p.provider]}</p>
        {:else if rowNotice[p.provider]}
          <p class="text-sm text-green-400">{rowNotice[p.provider]}</p>
        {/if}
      </div>
    {/each}
  {/if}
</div>
