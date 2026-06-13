<script lang="ts">
  import { api } from '$lib/api';

  // Full per-user data Export (#19, ADR-0006): one tap downloads a ZIP holding
  // a JSON document plus one CSV per record type — every Session, Set, Workout,
  // Metric, Program, PR and the Gym Profile. The data-ownership guarantee of a
  // self-hosted platform. The backend streams the archive (GET /api/export);
  // here we just trigger the download and show progress/errors.

  let busy = $state(false);
  let error = $state('');
  let done = $state(false);

  async function exportData() {
    busy = true;
    error = '';
    done = false;
    try {
      await api.download('/api/export');
      done = true;
    } catch (e) {
      error =
        e instanceof Error
          ? e.message
          : 'Export failed. Please try again.';
    } finally {
      busy = false;
    }
  }
</script>

<div class="bg-surface-800 rounded-xl border border-surface-700 p-6 space-y-4">
  <p class="text-sm text-surface-400">
    Download a complete archive of your data — every session, set, workout,
    metric, program and personal record — as JSON and CSV in a single ZIP. It's
    yours to keep, move, or back up.
  </p>

  <button
    type="button"
    onclick={exportData}
    disabled={busy}
    class="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-4 py-2.5 bg-primary-500 hover:bg-primary-600 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors"
  >
    {#if busy}
      <span
        class="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin"
        aria-hidden="true"
      ></span>
      Preparing your archive…
    {:else}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        class="w-4 h-4"
        viewBox="0 0 20 20"
        fill="currentColor"
        aria-hidden="true"
      >
        <path
          fill-rule="evenodd"
          d="M10 3a.75.75 0 0 1 .75.75v6.638l1.96-2.158a.75.75 0 1 1 1.08 1.04l-3.25 3.5a.75.75 0 0 1-1.08 0l-3.25-3.5a.75.75 0 1 1 1.08-1.04l1.96 2.158V3.75A.75.75 0 0 1 10 3Z"
          clip-rule="evenodd"
        />
        <path
          d="M3.5 12.75a.75.75 0 0 0-1.5 0v2.5A2.75 2.75 0 0 0 4.75 18h10.5A2.75 2.75 0 0 0 18 15.25v-2.5a.75.75 0 0 0-1.5 0v2.5c0 .69-.56 1.25-1.25 1.25H4.75c-.69 0-1.25-.56-1.25-1.25v-2.5Z"
        />
      </svg>
      Export all my data
    {/if}
  </button>

  {#if done}
    <p class="text-sm text-green-400">
      Your archive has been downloaded.
    </p>
  {/if}

  {#if error}
    <div class="p-3 rounded-lg bg-red-500/10 border border-red-500/20">
      <p class="text-sm text-red-400">{error}</p>
    </div>
  {/if}
</div>
