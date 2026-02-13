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
  let error = $state<string | null>(null);
  let loadVersion = $state(0);

  $effect(() => {
    loadDashboard(dateRange.startISO, dateRange.endISO, dateRange.resolution);
  });

  async function loadDashboard(start: string, end: string, resolution: string) {
    loading = true;
    error = null;
    const version = ++loadVersion;

    // Reset state so stale data from a previous range doesn't persist
    summary = null;
    rings = null;
    stepsData = null;
    energyData = null;
    hrData = null;
    exerciseData = null;

    try {
      // Batch requests to avoid overwhelming the backend/DB with concurrent connections.
      // Batch 1: summary + activity rings
      const [summaryRes, ringsRes] = await Promise.allSettled([
        api.get<DashboardSummary>(`/api/dashboard/summary?start=${start}&end=${end}`),
        api.get<ActivityRingData[]>(`/api/activity/rings?start=${start}&end=${end}`),
      ]);
      if (version !== loadVersion) return;

      if (summaryRes.status === 'fulfilled') summary = summaryRes.value;
      if (ringsRes.status === 'fulfilled' && ringsRes.value.length > 0) rings = ringsRes.value[0];

      // Batch 2: steps + energy sparklines
      const [stepsRes, energyRes] = await Promise.allSettled([
        api.get<MetricResponse>(`/api/metrics/StepCount?start=${start}&end=${end}&resolution=${resolution}`),
        api.get<MetricResponse>(`/api/metrics/ActiveEnergyBurned?start=${start}&end=${end}&resolution=${resolution}`),
      ]);
      if (version !== loadVersion) return;

      if (stepsRes.status === 'fulfilled') stepsData = stepsRes.value;
      if (energyRes.status === 'fulfilled') energyData = energyRes.value;

      // Batch 3: heart rate + exercise sparklines
      const [hrRes, exerciseRes] = await Promise.allSettled([
        api.get<MetricResponse>(`/api/metrics/HeartRate?start=${start}&end=${end}&resolution=${resolution}`),
        api.get<MetricResponse>(`/api/metrics/AppleExerciseTime?start=${start}&end=${end}&resolution=${resolution}`),
      ]);
      if (version !== loadVersion) return;

      if (hrRes.status === 'fulfilled') hrData = hrRes.value;
      if (exerciseRes.status === 'fulfilled') exerciseData = exerciseRes.value;

      // Check if all requests failed
      const results = [summaryRes, ringsRes, stepsRes, energyRes, hrRes, exerciseRes];
      const allFailed = results.every(r => r.status === 'rejected');
      if (allFailed) {
        const firstError = results.find(r => r.status === 'rejected');
        error = firstError?.status === 'rejected' && firstError.reason instanceof Error
          ? firstError.reason.message
          : 'Failed to load dashboard data';
      }
    } catch {
      if (version === loadVersion) {
        error = 'Failed to load dashboard data';
      }
    } finally {
      if (version === loadVersion) {
        loading = false;
      }
    }
  }

  let stepsSparkline = $derived(stepsData?.data.map((d) => d.value) ?? []);
  let energySparkline = $derived(energyData?.data.map((d) => d.value) ?? []);
  let hrSparkline = $derived(hrData?.data.map((d) => d.value) ?? []);
  let exerciseSparkline = $derived(exerciseData?.data.map((d) => d.value) ?? []);

  // Derive aggregate values from metrics data (updates with date range)
  // falling back to summary data for fields only the summary endpoint provides.
  let effectiveSummary = $derived<DashboardSummary>({
    steps_today: stepsData?.stats.total ?? summary?.steps_today ?? null,
    active_energy_today: energyData?.stats.total ?? summary?.active_energy_today ?? null,
    exercise_minutes_today: exerciseData?.stats.total ?? summary?.exercise_minutes_today ?? null,
    stand_hours_today: summary?.stand_hours_today ?? null,
    resting_hr: summary?.resting_hr ?? null,
    hrv: summary?.hrv ?? null,
    spo2: summary?.spo2 ?? null,
    sleep_hours_last_night: summary?.sleep_hours_last_night ?? null,
  });
</script>

<div class="space-y-6">
  {#if error && !loading}
    <div class="rounded-xl bg-red-900/20 border border-red-700/50 p-4" data-testid="dashboard-error">
      <p class="text-red-400 text-sm">{error}</p>
    </div>
  {/if}

  <!-- Top row: Activity Rings + Today Summary -->
  <div class="grid grid-cols-1 lg:grid-cols-[auto_1fr] gap-6">
    <!-- Activity Rings -->
    <div class="rounded-xl bg-surface-800 border border-surface-700/50 p-6 flex items-center justify-center" data-testid="dashboard-activity-rings">
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
    <TodaySummary summary={effectiveSummary} {loading} />
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
        value={effectiveSummary.steps_today}
        unit="steps"
        trend={stepsData?.stats.trend_pct ?? null}
        sparklineData={stepsSparkline}
        icon="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"
        color="#10b981"
      />
      <MetricCard
        title="Active Energy"
        value={effectiveSummary.active_energy_today != null ? Math.round(effectiveSummary.active_energy_today) : null}
        unit="kcal"
        trend={energyData?.stats.trend_pct ?? null}
        sparklineData={energySparkline}
        icon="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z"
        color="#f59e0b"
      />
      <MetricCard
        title="Heart Rate"
        value={hrData?.stats.avg != null ? Math.round(hrData.stats.avg) : (effectiveSummary.resting_hr != null ? Math.round(effectiveSummary.resting_hr) : null)}
        unit="bpm"
        trend={hrData?.stats.trend_pct ?? null}
        sparklineData={hrSparkline}
        icon="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"
        color="#ef4444"
      />
      <MetricCard
        title="Exercise"
        value={effectiveSummary.exercise_minutes_today != null ? Math.round(effectiveSummary.exercise_minutes_today) : null}
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
    <SleepSummary summary={effectiveSummary} {loading} />
  </div>
</div>
