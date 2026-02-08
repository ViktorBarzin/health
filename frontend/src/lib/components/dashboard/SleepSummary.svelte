<script lang="ts">
  import { api } from '$lib/api';
  import type { DashboardSummary } from '$lib/types';

  let summary = $state<DashboardSummary | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  $effect(() => {
    loadSleep();
  });

  async function loadSleep() {
    loading = true;
    error = null;
    try {
      summary = await api.get<DashboardSummary>('/api/dashboard/summary');
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load sleep data';
    } finally {
      loading = false;
    }
  }

  let hours = $derived(summary ? Math.floor(summary.sleep_hours_last_night) : 0);
  let minutes = $derived(summary ? Math.round((summary.sleep_hours_last_night % 1) * 60) : 0);

  let qualityLabel = $derived.by(() => {
    if (!summary) return '';
    const h = summary.sleep_hours_last_night;
    if (h >= 8) return 'Excellent';
    if (h >= 7) return 'Good';
    if (h >= 6) return 'Fair';
    return 'Poor';
  });

  let qualityColor = $derived.by(() => {
    if (!summary) return 'text-surface-400';
    const h = summary.sleep_hours_last_night;
    if (h >= 8) return 'text-green-400';
    if (h >= 7) return 'text-blue-400';
    if (h >= 6) return 'text-yellow-400';
    return 'text-red-400';
  });

  let barPercent = $derived(
    summary ? Math.min((summary.sleep_hours_last_night / 9) * 100, 100) : 0
  );
</script>

<div class="rounded-xl bg-surface-800 border border-surface-700/50 p-4">
  <div class="flex items-center gap-2 mb-4">
    <div class="w-8 h-8 rounded-lg bg-[var(--color-sleep)]/15 flex items-center justify-center">
      <svg class="w-4 h-4 text-[var(--color-sleep)]" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
      </svg>
    </div>
    <h3 class="text-sm font-semibold text-surface-200">Sleep</h3>
    <span class="ml-auto text-xs text-surface-500">Last night</span>
  </div>

  {#if loading}
    <div class="animate-pulse space-y-3">
      <div class="h-10 w-28 bg-surface-700 rounded"></div>
      <div class="h-3 w-full bg-surface-700 rounded"></div>
      <div class="h-4 w-16 bg-surface-700 rounded"></div>
    </div>
  {:else if error}
    <div class="text-center py-4">
      <p class="text-red-400 text-sm">{error}</p>
      <button
        onclick={loadSleep}
        class="mt-2 text-xs text-primary-400 hover:text-primary-300 underline"
      >
        Retry
      </button>
    </div>
  {:else if summary}
    <!-- Hours slept -->
    <div class="flex items-baseline gap-1 mb-3">
      <span class="text-3xl font-bold text-surface-100">{hours}</span>
      <span class="text-lg text-surface-400">h</span>
      <span class="text-3xl font-bold text-surface-100 ml-1">{minutes}</span>
      <span class="text-lg text-surface-400">m</span>
    </div>

    <!-- Progress bar -->
    <div class="w-full h-2 bg-surface-700 rounded-full overflow-hidden mb-3">
      <div
        class="h-full rounded-full transition-all duration-700 ease-out"
        style="width: {barPercent}%; background-color: var(--color-sleep);"
      ></div>
    </div>

    <!-- Quality indicator -->
    <div class="flex items-center justify-between">
      <span class="text-sm {qualityColor} font-medium">{qualityLabel}</span>
      <span class="text-xs text-surface-500">Goal: 8h</span>
    </div>
  {/if}
</div>
