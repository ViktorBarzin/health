<script lang="ts">
  import { api } from '$lib/api';
  import type {
    DashboardSummary,
    ActivityRingData,
    MetricAvailable,
    MetricResponse,
  } from '$lib/types';
  import { dateRange } from '$lib/stores/date-range.svelte';
  import { DEFAULT_MAX_POINTS, downsampleSeries } from '$lib/dashboard';
  import ActivityRings from '$lib/components/charts/ActivityRings.svelte';
  import MetricCard from '$lib/components/dashboard/MetricCard.svelte';
  import TodaySummary from '$lib/components/dashboard/TodaySummary.svelte';
  import RecentWorkouts from '$lib/components/dashboard/RecentWorkouts.svelte';
  import SleepSummary from '$lib/components/dashboard/SleepSummary.svelte';
  import ReadinessCard from '$lib/components/dashboard/ReadinessCard.svelte';

  let summary = $state<DashboardSummary | null>(null);
  let rings = $state<ActivityRingData | null>(null);
  let stepsData = $state<MetricResponse | null>(null);
  let energyData = $state<MetricResponse | null>(null);
  let hrData = $state<MetricResponse | null>(null);
  let exerciseData = $state<MetricResponse | null>(null);

  // Per-source loading flags so every card renders its OWN loading state and
  // fills in independently as its request resolves — the page is interactive
  // immediately and never blocks the whole dashboard on the slowest request.
  let summaryLoading = $state(true);
  let ringsLoading = $state(true);
  let stepsLoading = $state(true);
  let energyLoading = $state(true);
  let hrLoading = $state(true);
  let exerciseLoading = $state(true);

  let error = $state<string | null>(null);
  let loadVersion = $state(0);
  // Gate the first data load until the data-driven default window is resolved
  // (so we don't fire a wasted fetch over the empty last-30-days first).
  let windowReady = $state(false);
  let initStarted = false;

  // Resolve the initial window from the user's latest available data, then let
  // the reactive effect below drive the actual data load. Only the FIRST load
  // is clamped; manual preset/range choices flip dateRange.defaultApplied and
  // are respected. A failure here just falls through to the store's default.
  async function resolveInitialWindow() {
    if (dateRange.defaultApplied) {
      windowReady = true;
      return;
    }
    try {
      const metrics = await api.get<MetricAvailable[]>('/api/metrics/available');
      dateRange.applyDefaultWindow(metrics);
    } catch {
      // Leave the store's default window in place.
    } finally {
      windowReady = true;
    }
  }

  $effect(() => {
    // One-shot: resolve the initial window exactly once on mount.
    if (initStarted) return;
    initStarted = true;
    resolveInitialWindow();
  });

  $effect(() => {
    // Touch the reactive deps so a range/resolution change re-loads.
    const start = dateRange.startISO;
    const end = dateRange.endISO;
    const resolution = dateRange.resolution;
    if (!windowReady) return;
    loadDashboard(start, end, resolution);
  });

  function loadDashboard(start: string, end: string, resolution: string) {
    error = null;
    const version = ++loadVersion;

    // Reset per-source state + loading so stale data from a previous range
    // doesn't persist while the new range's requests are in flight.
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
      api.get<MetricResponse>(
        `/api/metrics/${type}?start=${start}&end=${end}&resolution=${resolution}`,
      );

    // Fire ALL requests concurrently (one batch) and render each card as its own
    // response arrives — total latency ≈ the slowest single request, not the sum
    // of three serial round-trips. Each .then/.catch is version-guarded so a fast
    // range change can't render stale data, and each settles its own loading flag.
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

    // Surface an error banner only when EVERY request failed (otherwise the
    // cards that loaded stand on their own).
    Promise.allSettled([summaryP, ringsP, stepsP, energyP, hrP, exerciseP]).then(
      () => {
        if (!fresh()) return;
        const anyData =
          summary !== null ||
          rings !== null ||
          stepsData !== null ||
          energyData !== null ||
          hrData !== null ||
          exerciseData !== null;
        if (!anyData) error = 'Failed to load dashboard data';
      },
    );
  }

  // Sparklines: cap the points actually drawn so a wide window can't flood the
  // renderer (day-resolution rollups are already small; this protects `raw`/all).
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
  {#if error}
    <div class="rounded-xl bg-red-900/20 border border-red-700/50 p-4">
      <p class="text-red-400 text-sm">{error}</p>
    </div>
  {/if}

  <!-- Top row: Activity Rings + Today Summary -->
  <div class="grid grid-cols-1 lg:grid-cols-[auto_1fr] gap-6">
    <!-- Activity Rings -->
    <div class="rounded-xl bg-surface-800 border border-surface-700/50 p-6 flex items-center justify-center">
      {#if ringsLoading}
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

    <!-- Today summary (vital signs gate on the summary request; activity values
         fill from the metric requests as they arrive). -->
    <TodaySummary summary={effectiveSummary} loading={summaryLoading} />
  </div>

  <!-- Metric cards with sparklines — each fills in independently. -->
  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
    {#if stepsLoading}
      <div class="rounded-xl bg-surface-800 p-4 border border-surface-700/50 animate-pulse">
        <div class="flex items-center gap-2 mb-3"><div class="w-8 h-8 rounded-lg bg-surface-700"></div><div class="h-4 w-20 bg-surface-700 rounded"></div></div>
        <div class="h-8 w-24 bg-surface-700 rounded mb-2"></div>
        <div class="h-6 w-full bg-surface-700 rounded mt-3"></div>
      </div>
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
    {/if}

    {#if energyLoading}
      <div class="rounded-xl bg-surface-800 p-4 border border-surface-700/50 animate-pulse">
        <div class="flex items-center gap-2 mb-3"><div class="w-8 h-8 rounded-lg bg-surface-700"></div><div class="h-4 w-20 bg-surface-700 rounded"></div></div>
        <div class="h-8 w-24 bg-surface-700 rounded mb-2"></div>
        <div class="h-6 w-full bg-surface-700 rounded mt-3"></div>
      </div>
    {:else}
      <MetricCard
        title="Active Energy"
        value={effectiveSummary.active_energy_today != null ? Math.round(effectiveSummary.active_energy_today) : null}
        unit="kcal"
        trend={energyData?.stats.trend_pct ?? null}
        sparklineData={energySparkline}
        icon="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z"
        color="#f59e0b"
      />
    {/if}

    {#if hrLoading}
      <div class="rounded-xl bg-surface-800 p-4 border border-surface-700/50 animate-pulse">
        <div class="flex items-center gap-2 mb-3"><div class="w-8 h-8 rounded-lg bg-surface-700"></div><div class="h-4 w-20 bg-surface-700 rounded"></div></div>
        <div class="h-8 w-24 bg-surface-700 rounded mb-2"></div>
        <div class="h-6 w-full bg-surface-700 rounded mt-3"></div>
      </div>
    {:else}
      <MetricCard
        title="Heart Rate"
        value={hrData?.stats.avg != null ? Math.round(hrData.stats.avg) : (effectiveSummary.resting_hr != null ? Math.round(effectiveSummary.resting_hr) : null)}
        unit="bpm"
        trend={hrData?.stats.trend_pct ?? null}
        sparklineData={hrSparkline}
        icon="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"
        color="#ef4444"
      />
    {/if}

    {#if exerciseLoading}
      <div class="rounded-xl bg-surface-800 p-4 border border-surface-700/50 animate-pulse">
        <div class="flex items-center gap-2 mb-3"><div class="w-8 h-8 rounded-lg bg-surface-700"></div><div class="h-4 w-20 bg-surface-700 rounded"></div></div>
        <div class="h-8 w-24 bg-surface-700 rounded mb-2"></div>
        <div class="h-6 w-full bg-surface-700 rounded mt-3"></div>
      </div>
    {:else}
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

  <!-- Bottom row: Recent Workouts + Readiness/Sleep insights -->
  <div class="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
    <RecentWorkouts start={dateRange.startISO} end={dateRange.endISO} />
    <div class="space-y-4">
      <ReadinessCard />
      <SleepSummary summary={effectiveSummary} loading={summaryLoading} />
    </div>
  </div>
</div>
