<script lang="ts">
  import type { DashboardSummary } from '$lib/types';
  import MetricCard from './MetricCard.svelte';

  interface Props {
    summary: DashboardSummary | null;
    loading: boolean;
  }

  let { summary, loading }: Props = $props();
</script>

{#if loading}
  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
    {#each Array(4) as _}
      <div class="rounded-xl bg-surface-800 p-4 border border-surface-700/50 animate-pulse">
        <div class="flex items-center gap-2 mb-3">
          <div class="w-8 h-8 rounded-lg bg-surface-700"></div>
          <div class="h-4 w-20 bg-surface-700 rounded"></div>
        </div>
        <div class="h-8 w-24 bg-surface-700 rounded mb-2"></div>
        <div class="h-4 w-full bg-surface-700 rounded"></div>
      </div>
    {/each}
  </div>

  <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-4">
    {#each Array(3) as _}
      <div class="rounded-xl bg-surface-800 p-4 border border-surface-700/50 animate-pulse">
        <div class="h-4 w-20 bg-surface-700 rounded mb-2"></div>
        <div class="h-8 w-16 bg-surface-700 rounded"></div>
      </div>
    {/each}
  </div>
{:else if summary}
  <!-- Activity metrics -->
  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
    <MetricCard
      title="Steps"
      value={summary.steps_today}
      unit="steps"
      icon="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"
      color="#10b981"
    />
    <MetricCard
      title="Active Energy"
      value={summary.active_energy_today != null ? Math.round(summary.active_energy_today) : null}
      unit="kcal"
      icon="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z"
      color="#f59e0b"
    />
    <MetricCard
      title="Exercise"
      value={summary.exercise_minutes_today}
      unit="min"
      icon="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
      color="#22c55e"
    />
    <MetricCard
      title="Stand Hours"
      value={summary.stand_hours_today}
      unit="hrs"
      icon="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
      color="#3b82f6"
    />
  </div>

  <!-- Vital signs -->
  <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-4">
    <MetricCard
      title="Resting HR"
      value={summary.resting_hr}
      unit="bpm"
      icon="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"
      color="#ef4444"
    />
    <MetricCard
      title="HRV"
      value={summary.hrv}
      unit="ms"
      icon="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
      color="#8b5cf6"
    />
    <MetricCard
      title="SpO2"
      value={summary.spo2}
      unit="%"
      icon="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"
      color="#06b6d4"
    />
  </div>
{/if}
