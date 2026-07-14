<script lang="ts">
  // Progress — the review surface (ADR-0008). The health-metrics dashboard moved
  // here from the home route, and the date-range control lives here (where a range
  // is meaningful) rather than in the global shell. Slice 7 bespoke-redesigns each
  // chart; this preserves the full dashboard with no loss of function.
  import { api } from '$lib/api';
  import type {
    DashboardSummary,
    ActivityRingData,
    MetricAvailable,
    MetricResponse,
  } from '$lib/types';
  import { dateRange } from '$lib/stores/date-range.svelte';
  import { DEFAULT_MAX_POINTS, downsampleSeries } from '$lib/dashboard';
  import { MORE_GROUPS } from '$lib/nav';
  import DateRangePicker from '$lib/components/layout/DateRangePicker.svelte';
  import ActivityRings from '$lib/components/charts/ActivityRings.svelte';
  import MetricCard from '$lib/components/dashboard/MetricCard.svelte';
  import TodaySummary from '$lib/components/dashboard/TodaySummary.svelte';
  import RecentWorkouts from '$lib/components/dashboard/RecentWorkouts.svelte';
  import SleepSummary from '$lib/components/dashboard/SleepSummary.svelte';
  import ReadinessCard from '$lib/components/dashboard/ReadinessCard.svelte';
  import BodyCompVsVolume from '$lib/components/progress/BodyCompVsVolume.svelte';

  const reviewItems = MORE_GROUPS.find((g) => g.title === 'Progress')?.items ?? [];

  let summary = $state<DashboardSummary | null>(null);
  let rings = $state<ActivityRingData | null>(null);
  let stepsData = $state<MetricResponse | null>(null);
  let energyData = $state<MetricResponse | null>(null);
  let hrData = $state<MetricResponse | null>(null);
  let exerciseData = $state<MetricResponse | null>(null);

  let summaryLoading = $state(true);
  let ringsLoading = $state(true);
  let stepsLoading = $state(true);
  let energyLoading = $state(true);
  let hrLoading = $state(true);
  let exerciseLoading = $state(true);

  let error = $state<string | null>(null);
  let loadVersion = $state(0);
  let windowReady = $state(false);
  let initStarted = false;

  async function resolveInitialWindow() {
    if (dateRange.defaultApplied) {
      windowReady = true;
      return;
    }
    try {
      const metrics = await api.get<MetricAvailable[]>('/api/metrics/available');
      dateRange.applyDefaultWindow(metrics);
    } catch {
      /* leave the store default */
    } finally {
      windowReady = true;
    }
  }

  $effect(() => {
    if (initStarted) return;
    initStarted = true;
    resolveInitialWindow();
  });

  $effect(() => {
    const start = dateRange.startISO;
    const end = dateRange.endISO;
    const resolution = dateRange.resolution;
    if (!windowReady) return;
    loadDashboard(start, end, resolution);
  });

  function loadDashboard(start: string, end: string, resolution: string) {
    error = null;
    const version = ++loadVersion;
    summary = null;
    rings = null;
    stepsData = null;
    energyData = null;
    hrData = null;
    exerciseData = null;
    summaryLoading = true;
    ringsLoading = true;
    stepsLoading = true;
    energyLoading = true;
    hrLoading = true;
    exerciseLoading = true;

    const fresh = () => version === loadVersion;
    const metric = (type: string) =>
      api.get<MetricResponse>(`/api/metrics/${type}?start=${start}&end=${end}&resolution=${resolution}`);

    const summaryP = api
      .get<DashboardSummary>(`/api/dashboard/summary?start=${start}&end=${end}`)
      .then((res) => { if (fresh()) summary = res; })
      .catch(() => {})
      .finally(() => { if (fresh()) summaryLoading = false; });
    const ringsP = api
      .get<ActivityRingData[]>(`/api/activity/rings?start=${start}&end=${end}`)
      .then((res) => { if (fresh() && res.length > 0) rings = res[0]; })
      .catch(() => {})
      .finally(() => { if (fresh()) ringsLoading = false; });
    const stepsP = metric('StepCount')
      .then((res) => { if (fresh()) stepsData = res; })
      .catch(() => {})
      .finally(() => { if (fresh()) stepsLoading = false; });
    const energyP = metric('ActiveEnergyBurned')
      .then((res) => { if (fresh()) energyData = res; })
      .catch(() => {})
      .finally(() => { if (fresh()) energyLoading = false; });
    const hrP = metric('HeartRate')
      .then((res) => { if (fresh()) hrData = res; })
      .catch(() => {})
      .finally(() => { if (fresh()) hrLoading = false; });
    const exerciseP = metric('AppleExerciseTime')
      .then((res) => { if (fresh()) exerciseData = res; })
      .catch(() => {})
      .finally(() => { if (fresh()) exerciseLoading = false; });

    Promise.allSettled([summaryP, ringsP, stepsP, energyP, hrP, exerciseP]).then(() => {
      if (!fresh()) return;
      const anyData =
        summary !== null || rings !== null || stepsData !== null ||
        energyData !== null || hrData !== null || exerciseData !== null;
      if (!anyData) error = 'Failed to load dashboard data';
    });
  }

  let stepsSparkline = $derived(
    downsampleSeries(stepsData?.data ?? [], DEFAULT_MAX_POINTS).map((d) => d.value),
  );
  let energySparkline = $derived(
    downsampleSeries(energyData?.data ?? [], DEFAULT_MAX_POINTS).map((d) => d.value),
  );
  let hrSparkline = $derived(
    downsampleSeries(hrData?.data ?? [], DEFAULT_MAX_POINTS).map((d) => d.value),
  );
  let exerciseSparkline = $derived(
    downsampleSeries(exerciseData?.data ?? [], DEFAULT_MAX_POINTS).map((d) => d.value),
  );

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

<div class="mx-auto max-w-5xl space-y-6">
  <header class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
    <div>
      <h1 class="text-2xl font-semibold tracking-tight text-ink">Progress</h1>
      <p class="mt-0.5 text-sm text-ink-2">Your training and health history.</p>
    </div>
    <DateRangePicker />
  </header>

  <!-- Jump to a review area. -->
  <div class="flex flex-wrap gap-2">
    {#each reviewItems as item (item.href)}
      <a
        href={item.href}
        class="inline-flex items-center gap-2 rounded-full border border-edge bg-panel-2 px-3.5 py-2 text-sm font-medium text-ink-2 transition-colors hover:text-ink"
      >
        <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.6">
          <path stroke-linecap="round" stroke-linejoin="round" d={item.icon} />
        </svg>
        {item.label}
      </a>
    {/each}
  </div>

  {#if error}
    <div class="rounded-xl border border-danger/40 bg-danger/10 p-4">
      <p class="text-sm text-danger">{error}</p>
    </div>
  {/if}

  <div class="grid grid-cols-1 gap-6 lg:grid-cols-[auto_1fr]">
    <div class="flex items-center justify-center rounded-2xl border border-edge bg-panel p-6">
      {#if ringsLoading}
        <div class="h-[140px] w-[140px] animate-pulse rounded-full bg-panel-2"></div>
      {:else if rings}
        <ActivityRings data={rings} size={140} />
      {:else}
        <div class="grid h-[140px] w-[140px] place-items-center rounded-full border-4 border-edge">
          <span class="text-sm text-ink-3">No data</span>
        </div>
      {/if}
    </div>
    <TodaySummary summary={effectiveSummary} loading={summaryLoading} />
  </div>

  <div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
    {#if stepsLoading}
      <div class="h-32 animate-pulse rounded-2xl border border-edge bg-panel"></div>
    {:else}
      <MetricCard title="Steps" value={effectiveSummary.steps_today} unit="steps" trend={stepsData?.stats.trend_pct ?? null} sparklineData={stepsSparkline} icon="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" color="#2fd07a" />
    {/if}
    {#if energyLoading}
      <div class="h-32 animate-pulse rounded-2xl border border-edge bg-panel"></div>
    {:else}
      <MetricCard title="Active Energy" value={effectiveSummary.active_energy_today != null ? Math.round(effectiveSummary.active_energy_today) : null} unit="kcal" trend={energyData?.stats.trend_pct ?? null} sparklineData={energySparkline} icon="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z" color="#f9a23b" />
    {/if}
    {#if hrLoading}
      <div class="h-32 animate-pulse rounded-2xl border border-edge bg-panel"></div>
    {:else}
      <MetricCard title="Heart Rate" value={hrData?.stats.avg != null ? Math.round(hrData.stats.avg) : effectiveSummary.resting_hr != null ? Math.round(effectiveSummary.resting_hr) : null} unit="bpm" trend={hrData?.stats.trend_pct ?? null} sparklineData={hrSparkline} icon="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" color="#fb5d6b" />
    {/if}
    {#if exerciseLoading}
      <div class="h-32 animate-pulse rounded-2xl border border-edge bg-panel"></div>
    {:else}
      <MetricCard title="Exercise" value={effectiveSummary.exercise_minutes_today != null ? Math.round(effectiveSummary.exercise_minutes_today) : null} unit="min" trend={exerciseData?.stats.trend_pct ?? null} sparklineData={exerciseSparkline} icon="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" color="#ff7849" />
    {/if}
  </div>

  <!-- Body comp vs training volume (plan M6): the correlation overlay -->
  <BodyCompVsVolume />

  <div class="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
    <RecentWorkouts start={dateRange.startISO} end={dateRange.endISO} />
    <div class="space-y-4">
      <ReadinessCard />
      <SleepSummary summary={effectiveSummary} loading={summaryLoading} />
    </div>
  </div>
</div>
