<script lang="ts">
  import { api } from '$lib/api';
  import type { MetricAvailable } from '$lib/types';
  import { METRIC_LABELS, METRIC_ICONS, METRIC_UNITS } from '$lib/utils/constants';
  import { formatNumber, formatDate } from '$lib/utils/format';

  let metrics = $state<MetricAvailable[]>([]);
  let loading = $state(true);
  let error = $state('');
  let search = $state('');

  const CATEGORIES: Record<string, string[]> = {
    'Vitals': ['HeartRate', 'RestingHeartRate', 'HeartRateVariabilitySDNN', 'OxygenSaturation', 'RespiratoryRate', 'BloodPressureSystolic', 'BloodPressureDiastolic', 'BodyTemperature', 'BloodGlucose'],
    'Activity': ['StepCount', 'ActiveEnergyBurned', 'BasalEnergyBurned', 'DistanceWalkingRunning', 'DistanceCycling', 'DistanceSwimming', 'FlightsClimbed', 'AppleExerciseTime', 'AppleStandTime', 'AppleStandHour', 'VO2Max'],
    'Body': ['BodyMass', 'BodyMassIndex', 'BodyFatPercentage', 'LeanBodyMass', 'Height'],
    'Sleep & Mindfulness': ['SleepAnalysis', 'MindfulSession'],
    'Nutrition': ['DietaryWater', 'DietaryEnergyConsumed', 'DietaryProtein', 'DietaryCarbohydrates', 'DietaryFatTotal', 'DietaryCaffeine'],
    'Mobility': ['WalkingHeartRateAverage', 'WalkingSpeed', 'WalkingStepLength', 'WalkingDoubleSupportPercentage', 'WalkingAsymmetryPercentage', 'SixMinuteWalkTestDistance', 'StairAscentSpeed', 'StairDescentSpeed'],
    'Audio': ['EnvironmentalAudioExposure', 'HeadphoneAudioExposure'],
  };

  $effect(() => {
    loadMetrics();
  });

  async function loadMetrics() {
    loading = true;
    error = '';
    try {
      metrics = await api.get<MetricAvailable[]>('/api/metrics/available');
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load metrics';
    } finally {
      loading = false;
    }
  }

  function getLabel(type: string): string {
    return METRIC_LABELS[type] ?? type.replace(/([A-Z])/g, ' $1').trim();
  }

  function getIcon(type: string): string {
    return METRIC_ICONS[type] ?? '\u{1F4CA}';
  }

  let filteredMetrics = $derived(
    metrics.filter((m) => {
      if (!search) return true;
      const q = search.toLowerCase();
      return (
        m.metric_type.toLowerCase().includes(q) ||
        getLabel(m.metric_type).toLowerCase().includes(q)
      );
    })
  );

  function getCategoryForMetric(type: string): string {
    for (const [cat, types] of Object.entries(CATEGORIES)) {
      if (types.includes(type)) return cat;
    }
    return 'Other';
  }

  let groupedMetrics = $derived.by(() => {
    const groups = new Map<string, MetricAvailable[]>();
    for (const m of filteredMetrics) {
      const cat = getCategoryForMetric(m.metric_type);
      if (!groups.has(cat)) groups.set(cat, []);
      groups.get(cat)!.push(m);
    }
    // Sort categories by the predefined order
    const ordered = new Map<string, MetricAvailable[]>();
    for (const cat of [...Object.keys(CATEGORIES), 'Other']) {
      if (groups.has(cat)) {
        ordered.set(cat, groups.get(cat)!);
      }
    }
    return ordered;
  });
</script>

<div class="space-y-6">
  <!-- Search bar -->
  <div class="relative">
    <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-surface-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
    <input
      type="text"
      bind:value={search}
      placeholder="Search metrics..."
      data-testid="metrics-search-input"
      class="w-full pl-10 pr-4 py-2.5 bg-surface-800 border border-surface-700 rounded-lg
             text-surface-100 placeholder-surface-500 text-sm
             focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500
             transition-colors"
    />
  </div>

  {#if loading}
    <!-- Loading skeleton -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {#each Array(8) as _}
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-5 animate-pulse">
          <div class="flex items-start justify-between">
            <div class="space-y-2">
              <div class="w-24 h-4 bg-surface-700 rounded"></div>
              <div class="w-16 h-3 bg-surface-700 rounded"></div>
            </div>
            <div class="w-8 h-8 bg-surface-700 rounded-lg"></div>
          </div>
          <div class="mt-4 space-y-2">
            <div class="w-20 h-5 bg-surface-700 rounded"></div>
            <div class="w-32 h-3 bg-surface-700 rounded"></div>
          </div>
        </div>
      {/each}
    </div>
  {:else if error}
    <div class="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400">{error}</p>
      <button
        class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm transition-colors"
        onclick={loadMetrics}
      >
        Retry
      </button>
    </div>
  {:else if filteredMetrics.length === 0}
    <div class="p-12 text-center">
      <svg class="w-12 h-12 text-surface-600 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
      </svg>
      <p class="text-surface-400 text-sm">No metrics found matching "{search}"</p>
    </div>
  {:else}
    {#each [...groupedMetrics] as [category, categoryMetrics]}
      <div>
        <h3 class="text-sm font-semibold text-surface-400 uppercase tracking-wider mb-3">{category}</h3>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {#each categoryMetrics as metric}
            <a
              href="/metrics/{metric.metric_type}"
              data-testid="metric-link-{metric.metric_type}"
              class="group bg-surface-800 rounded-xl border border-surface-700 p-5
                     hover:border-surface-600 hover:bg-surface-800/80 transition-all"
            >
              <div class="flex items-start justify-between">
                <div>
                  <h4 class="text-sm font-medium text-surface-200 group-hover:text-surface-100 transition-colors">
                    {getLabel(metric.metric_type)}
                  </h4>
                  <p class="text-xs text-surface-500 mt-0.5">{metric.unit || 'count'}</p>
                </div>
                <span class="text-xl" title={metric.metric_type}>
                  {getIcon(metric.metric_type)}
                </span>
              </div>
              <div class="mt-4">
                <p class="text-lg font-semibold text-surface-100">
                  {formatNumber(metric.count)}
                  <span class="text-xs text-surface-500 font-normal">records</span>
                </p>
                <p class="text-xs text-surface-500 mt-1">
                  Last updated {formatDate(metric.latest_time)}
                </p>
              </div>
            </a>
          {/each}
        </div>
      </div>
    {/each}
  {/if}
</div>
