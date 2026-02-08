<script lang="ts">
  import { api } from '$lib/api';
  import type { DashboardSummary, ActivityRingData, MetricResponse } from '$lib/types';
  import { dateRange } from '$lib/stores/date-range.svelte';
  import ActivityRings from '$lib/components/charts/ActivityRings.svelte';
  import MetricCard from '$lib/components/dashboard/MetricCard.svelte';
  import TodaySummary from '$lib/components/dashboard/TodaySummary.svelte';
  import RecentWorkouts from '$lib/components/dashboard/RecentWorkouts.svelte';
  import SleepSummary from '$lib/components/dashboard/SleepSummary.svelte';

  let summary = $state<DashboardSummary | null>(null);
  let rings = $state<ActivityRingData | null>(null);
  let stepsData = $state<MetricResponse | null>(null);
  let energyData = $state<MetricResponse | null>(null);
  let hrData = $state<MetricResponse | null>(null);
  let exerciseData = $state<MetricResponse | null>(null);
  let loading = $state(true);

  $effect(() => {
    const _s = dateRange.startISO;
    const _e = dateRange.endISO;
    const _r = dateRange.resolution;
    loadDashboard();
  });

  async function loadDashboard() {
    loading = true;

    const start = dateRange.startISO;
    const end = dateRange.endISO;
    const resolution = dateRange.resolution;

    try {
      const [summaryRes, ringsRes, stepsRes, energyRes, hrRes, exerciseRes] = await Promise.allSettled([
        api.get<DashboardSummary>(`/api/dashboard/summary?start=${start}&end=${end}`),
        api.get<ActivityRingData[]>(`/api/activity/rings?start=${start}&end=${end}`),
        api.get<MetricResponse>(`/api/metrics/steps?start=${start}&end=${end}&resolution=${resolution}`),
        api.get<MetricResponse>(`/api/metrics/active_energy?start=${start}&end=${end}&resolution=${resolution}`),
        api.get<MetricResponse>(`/api/metrics/heart_rate?start=${start}&end=${end}&resolution=${resolution}`),
        api.get<MetricResponse>(`/api/metrics/exercise_minutes?start=${start}&end=${end}&resolution=${resolution}`),
      ]);

      if (summaryRes.status === 'fulfilled') summary = summaryRes.value;
      if (ringsRes.status === 'fulfilled' && ringsRes.value.length > 0) rings = ringsRes.value[0];
      if (stepsRes.status === 'fulfilled') stepsData = stepsRes.value;
      if (energyRes.status === 'fulfilled') energyData = energyRes.value;
      if (hrRes.status === 'fulfilled') hrData = hrRes.value;
      if (exerciseRes.status === 'fulfilled') exerciseData = exerciseRes.value;
    } catch {
      // Individual errors are handled by settled results
    } finally {
      loading = false;
    }
  }

  let stepsSparkline = $derived(stepsData?.data.map((d) => d.value) ?? []);
  let energySparkline = $derived(energyData?.data.map((d) => d.value) ?? []);
  let hrSparkline = $derived(hrData?.data.map((d) => d.value) ?? []);
  let exerciseSparkline = $derived(exerciseData?.data.map((d) => d.value) ?? []);
</script>

<div class="space-y-6">
  <!-- Top row: Activity Rings + Today Summary -->
  <div class="grid grid-cols-1 lg:grid-cols-[auto_1fr] gap-6">
    <!-- Activity Rings -->
    <div class="rounded-xl bg-surface-800 border border-surface-700/50 p-6 flex items-center justify-center">
      {#if loading}
        <div class="animate-pulse w-[140px] h-[140px] rounded-full bg-surface-700"></div>
      {:else if rings}
        <ActivityRings data={rings} size={140} />
      {:else}
        <div class="text-center py-6">
          <div class="w-[140px] h-[140px] rounded-full border-4 border-surface-700 flex items-center justify-center mx-auto">
            <span class="text-surface-500 text-sm">No data</span>
          </div>
        </div>
      {/if}
    </div>

    <!-- Today summary -->
    <TodaySummary {summary} {loading} />
  </div>

  <!-- Metric cards with sparklines -->
  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
    {#if loading}
      {#each Array(4) as _}
        <div class="rounded-xl bg-surface-800 p-4 border border-surface-700/50 animate-pulse">
          <div class="flex items-center gap-2 mb-3">
            <div class="w-8 h-8 rounded-lg bg-surface-700"></div>
            <div class="h-4 w-20 bg-surface-700 rounded"></div>
          </div>
          <div class="h-8 w-24 bg-surface-700 rounded mb-2"></div>
          <div class="h-6 w-full bg-surface-700 rounded mt-3"></div>
        </div>
      {/each}
    {:else}
      <MetricCard
        title="Steps"
        value={summary?.steps_today ?? null}
        unit="steps"
        trend={stepsData?.stats.trend_pct ?? null}
        sparklineData={stepsSparkline}
        icon="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"
        color="#10b981"
      />
      <MetricCard
        title="Active Energy"
        value={summary?.active_energy_today != null ? Math.round(summary.active_energy_today) : null}
        unit="kcal"
        trend={energyData?.stats.trend_pct ?? null}
        sparklineData={energySparkline}
        icon="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z"
        color="#f59e0b"
      />
      <MetricCard
        title="Heart Rate"
        value={summary?.resting_hr ?? null}
        unit="bpm"
        trend={hrData?.stats.trend_pct ?? null}
        sparklineData={hrSparkline}
        icon="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"
        color="#ef4444"
      />
      <MetricCard
        title="Exercise"
        value={summary?.exercise_minutes_today ?? null}
        unit="min"
        trend={exerciseData?.stats.trend_pct ?? null}
        sparklineData={exerciseSparkline}
        icon="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
        color="#22c55e"
      />
    {/if}
  </div>

  <!-- Bottom row: Recent Workouts + Sleep Summary -->
  <div class="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
    <RecentWorkouts start={dateRange.startISO} end={dateRange.endISO} />
    <SleepSummary {summary} {loading} />
  </div>
</div>
