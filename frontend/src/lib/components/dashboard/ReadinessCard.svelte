<script lang="ts">
  import { api } from '$lib/api';
  import {
    componentSummary,
    formatScore,
    readinessBandLabel,
    readinessColor,
  } from '$lib/readiness';
  import type { ReadinessResponse } from '$lib/types';

  // The daily Readiness insight (#14, ADR-0004): a 0–100 biometric signal from
  // HRV, resting HR and sleep vs the user's own baseline — distinct from training
  // Recovery. Self-loads (it's a dashboard widget). Shows the score, band, and the
  // per-metric "X below your baseline" breakdown so the number is explainable.
  let readiness = $state<ReadinessResponse | null>(null);
  let loading = $state(true);

  $effect(() => {
    load();
  });

  async function load() {
    loading = true;
    try {
      readiness = await api.get<ReadinessResponse>('/api/readiness');
    } catch {
      readiness = null;
    } finally {
      loading = false;
    }
  }

  let score = $derived(readiness?.score ?? null);
  let band = $derived(readiness?.band ?? null);
  // Stroke fraction for the ring (0–1).
  let frac = $derived(score === null ? 0 : Math.max(0, Math.min(1, score / 100)));
  const R = 26;
  const C = 2 * Math.PI * R;
</script>

<div class="rounded-xl bg-surface-800 border border-surface-700/50 p-4">
  <div class="flex items-center justify-between mb-3">
    <h3 class="text-sm font-semibold text-surface-200">Readiness</h3>
    <span class="text-[10px] text-surface-500 uppercase tracking-wide">today</span>
  </div>

  {#if loading}
    <div class="flex items-center gap-4">
      <div class="w-16 h-16 rounded-full bg-surface-700 animate-pulse"></div>
      <div class="flex-1 space-y-2">
        <div class="h-3 w-24 bg-surface-700 rounded animate-pulse"></div>
        <div class="h-3 w-32 bg-surface-700 rounded animate-pulse"></div>
      </div>
    </div>
  {:else if !readiness || readiness.insufficient_data}
    <p class="text-xs text-surface-400 leading-relaxed">
      Not enough biometric data yet. Connect a watch or band (HRV, resting heart
      rate, sleep) and your daily readiness appears here.
    </p>
  {:else}
    <div class="flex items-center gap-4">
      <!-- Score ring -->
      <div class="relative w-16 h-16 shrink-0">
        <svg viewBox="0 0 64 64" class="w-16 h-16 -rotate-90">
          <circle cx="32" cy="32" r={R} fill="none" stroke="currentColor" stroke-width="6" class="text-surface-700" />
          <circle
            cx="32"
            cy="32"
            r={R}
            fill="none"
            stroke="currentColor"
            stroke-width="6"
            stroke-linecap="round"
            class={readinessColor(band)}
            stroke-dasharray={C}
            stroke-dashoffset={C * (1 - frac)}
          />
        </svg>
        <div class="absolute inset-0 flex items-center justify-center">
          <span class="text-lg font-bold tabular-nums {readinessColor(band)}">{formatScore(score)}</span>
        </div>
      </div>

      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold {readinessColor(band)}">{readinessBandLabel(band)}</p>
        <ul class="mt-1 space-y-0.5">
          {#each readiness.components as c (c.metric)}
            <li class="text-[11px] text-surface-400 truncate">{componentSummary(c)}</li>
          {/each}
        </ul>
      </div>
    </div>
  {/if}
</div>
