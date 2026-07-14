<script lang="ts">
  import { api } from '$lib/api';
  import { lastSyncSummary } from '$lib/connections';

  // Apple Health auto-sync (M7, ADR-0012): mint the per-user ingest token and
  // walk the ONE-TIME iOS Shortcut setup (workout-end + morning automations).
  // After that, health data flows in by itself — the token row's last_used_at
  // is the liveness signal ("Last sync 2h ago").
  interface TokenRead {
    id: string;
    label: string;
    prefix: string;
    created_at: string | null;
    last_used_at: string | null;
  }

  let tokens = $state<TokenRead[] | null>(null);
  let freshToken = $state<string | null>(null); // plaintext — shown once
  let busy = $state(false);
  let error = $state('');
  let guideOpen = $state(false);
  let copied = $state(false);

  $effect(() => {
    void load();
  });

  async function load() {
    try {
      tokens = await api.get<TokenRead[]>('/api/ingest/tokens');
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load sync state';
      tokens = tokens ?? [];
    }
  }

  async function mint() {
    if (busy) return;
    busy = true;
    error = '';
    try {
      const res = await api.post<TokenRead & { token: string }>(
        '/api/ingest/tokens',
        { label: 'iPhone' },
      );
      freshToken = res.token;
      guideOpen = true;
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to create the token';
    } finally {
      busy = false;
    }
  }

  async function revoke(id: string) {
    if (busy) return;
    busy = true;
    error = '';
    try {
      await api.delete(`/api/ingest/tokens/${id}`);
      freshToken = null;
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to revoke the token';
    } finally {
      busy = false;
    }
  }

  async function copyToken() {
    if (!freshToken) return;
    try {
      await navigator.clipboard.writeText(freshToken);
      copied = true;
      setTimeout(() => (copied = false), 2000);
    } catch {
      // Clipboard can be denied — the token stays visible for manual copy.
    }
  }

  const INGEST_URL = 'https://health-api.viktorbarzin.me/api/ingest/apple';
</script>

{#if error}
  <p class="text-sm text-red-400 mb-2">{error}</p>
{/if}

{#if tokens === null}
  <div class="h-12 bg-surface-800 rounded-lg animate-pulse"></div>
{:else}
  {#if tokens.length === 0}
    <div class="p-3 rounded-lg bg-surface-800 border border-surface-700">
      <p class="text-sm text-surface-300">
        One-time setup: create a sync token, add two iPhone automations, and your
        HRV, resting heart rate, sleep, weight and workouts import themselves —
        after every workout and every morning.
      </p>
      <button
        onclick={mint}
        disabled={busy}
        class="mt-3 w-full py-2.5 rounded-lg bg-primary-500 hover:bg-primary-600 text-sm font-semibold transition-colors disabled:opacity-50"
      >
        {busy ? 'Creating…' : 'Turn on auto-sync'}
      </button>
    </div>
  {:else}
    <ul class="space-y-1.5">
      {#each tokens as t (t.id)}
        <li class="flex items-center justify-between gap-3 p-3 rounded-lg bg-surface-800 border border-surface-700">
          <div class="min-w-0">
            <p class="text-sm font-medium text-surface-200">{t.label} <span class="text-surface-500 font-mono text-xs">{t.prefix}…</span></p>
            <p class="text-xs {t.last_used_at ? 'text-emerald-400/90' : 'text-amber-400/90'}">
              {lastSyncSummary(t.last_used_at)}
            </p>
          </div>
          <button
            onclick={() => revoke(t.id)}
            disabled={busy}
            class="shrink-0 px-2.5 py-1.5 rounded-lg text-xs font-medium text-surface-300 bg-surface-700 hover:bg-surface-600 transition-colors disabled:opacity-50"
          >
            Revoke
          </button>
        </li>
      {/each}
    </ul>
    <button
      onclick={() => (guideOpen = !guideOpen)}
      class="mt-2 text-[11px] font-medium text-primary-400 hover:text-primary-300"
    >
      {guideOpen ? 'Hide setup guide' : 'Show setup guide'}
    </button>
  {/if}

  {#if freshToken}
    <div class="mt-3 p-3 rounded-lg bg-primary-500/10 border border-primary-500/30">
      <p class="text-xs font-semibold text-primary-200 mb-1">
        Your sync token — copy it now, it won't be shown again:
      </p>
      <div class="flex items-center gap-2">
        <code class="flex-1 text-[11px] break-all text-surface-100 font-mono">{freshToken}</code>
        <button
          onclick={copyToken}
          class="shrink-0 px-2.5 py-1.5 rounded-lg bg-primary-500 text-xs font-semibold"
        >
          {copied ? 'Copied ✓' : 'Copy'}
        </button>
      </div>
    </div>
  {/if}

  {#if guideOpen}
    <div class="mt-3 p-3 rounded-lg bg-surface-800 border border-surface-700 space-y-3 text-xs text-surface-300 leading-relaxed">
      <p class="font-semibold text-surface-100">One-time setup on your iPhone (≈10 min)</p>

      <div>
        <p class="font-medium text-surface-200 mb-1">1 · Build the sync shortcut</p>
        <ol class="list-decimal ml-4 space-y-1">
          <li>Shortcuts app → <b>+</b> → name it <b>“Health Sync”</b>.</li>
          <li>Add <b>Find Health Samples</b> → type <b>Heart Rate Variability</b>, filter <i>Start Date is in the last 2 days</i>.</li>
          <li>Add <b>Repeat with Each</b> over the samples; inside add <b>Text</b>: <code>metric,HeartRateVariabilitySDNN,[Start Date],[Value],ms</code> (pick the variables from the sample).</li>
          <li>Repeat steps 2–3 for <b>Resting Heart Rate</b>, <b>Body Mass</b>, <b>Body Fat Percentage</b>, <b>Lean Body Mass</b> (line: <code>metric,&lt;Type&gt;,[Start Date],[Value],[Unit]</code>), for <b>Sleep Analysis</b> (line: <code>sleep,[Start Date],[End Date],[Value]</code>) and <b>Workouts</b> (line: <code>workout,[Workout Type],[Start Date],[End Date],[Active Energy],[Distance]</code>).</li>
          <li>Add <b>Combine Text</b> (all repeat results, separator <i>New Lines</i>).</li>
          <li>Add <b>Get Contents of URL</b>: URL <code>{INGEST_URL}</code>, Method <b>POST</b>, Headers → <code>Authorization: Bearer &lt;your token&gt;</code>, Request Body → <b>File</b> → the combined text.</li>
          <li>Run it once by hand — it should reply with counts like <code>{'{'}"metrics": 4 …{'}'}</code>, and “Last sync” above turns green.</li>
        </ol>
      </div>

      <div>
        <p class="font-medium text-surface-200 mb-1">2 · Automate it (twice)</p>
        <ol class="list-decimal ml-4 space-y-1">
          <li>Shortcuts → <b>Automation</b> → <b>+</b> → <b>Apple Watch Workout</b> → your workout types → <b>When workout ends</b> → <b>Run Immediately</b> → run <b>Health Sync</b>.</li>
          <li>Again: <b>+</b> → <b>Time of Day</b> → e.g. 09:00 daily → <b>Run Immediately</b> → run <b>Health Sync</b>.</li>
        </ol>
      </div>

      <p class="text-surface-500">
        Re-sends are free (the server de-duplicates), so overlapping runs never
        double-import. If the phone is locked when an automation fires, that run
        may carry nothing — the next one self-heals. Bulk history still goes
        through the export.zip import above.
      </p>
    </div>
  {/if}
{/if}
