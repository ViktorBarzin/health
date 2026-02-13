<script lang="ts">
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import type { WorkoutDetail, MetricResponse, MetricDataPoint } from '$lib/types';
  import { WORKOUT_LABELS } from '$lib/utils/constants';
  import { formatDate, formatDuration, formatDistance, formatNumber, formatEnergy } from '$lib/utils/format';
  import TimeSeriesChart from '$lib/components/charts/TimeSeriesChart.svelte';

  let workoutId = $derived($page.params.id);
  let workout = $state<WorkoutDetail | null>(null);
  let hrData = $state<MetricDataPoint[]>([]);
  let loading = $state(true);
  let error = $state('');
  let mapContainer: HTMLDivElement;
  let mapInstance: any = null;

  $effect(() => {
    const _id = workoutId;
    loadWorkout();
  });

  async function loadWorkout() {
    loading = true;
    error = '';
    try {
      workout = await api.get<WorkoutDetail>(`/api/workouts/${workoutId}`);

      // Load heart rate data for this workout's time range
      if (workout) {
        try {
          const startISO = new Date(workout.time).toISOString();
          const endISO = new Date(workout.end_time).toISOString();
          const hrResponse = await api.get<MetricResponse>(
            `/api/metrics/HeartRate?start=${startISO}&end=${endISO}&resolution=raw`
          );
          hrData = hrResponse.data;
        } catch {
          // Heart rate data may not be available
          hrData = [];
        }
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load workout';
    } finally {
      loading = false;
    }
  }

  const WORKOUT_ICONS: Record<string, string> = {
    Running: '\u{1F3C3}', Walking: '\u{1F6B6}', Cycling: '\u{1F6B4}', Swimming: '\u{1F3CA}',
    Hiking: '\u{26F0}', Yoga: '\u{1F9D8}', FunctionalStrengthTraining: '\u{1F4AA}',
    HighIntensityIntervalTraining: '\u{1F525}', TraditionalStrengthTraining: '\u{1F3CB}',
    Elliptical: '\u{1F6B2}', Rowing: '\u{1F6A3}', Dance: '\u{1F483}',
    Tennis: '\u{1F3BE}', Soccer: '\u{26BD}', Basketball: '\u{1F3C0}',
  };

  function getLabel(type: string): string {
    return WORKOUT_LABELS[type] ?? type.replace(/([A-Z])/g, ' $1').trim();
  }

  function getIcon(type: string): string {
    return WORKOUT_ICONS[type] ?? '\u{1F3C6}';
  }

  function calculatePace(distanceM: number, durationSec: number): string {
    if (distanceM <= 0 || durationSec <= 0) return '--';
    const minPerKm = (durationSec / 60) / (distanceM / 1000);
    const paceMin = Math.floor(minPerKm);
    const paceSec = Math.round((minPerKm - paceMin) * 60);
    return `${paceMin}:${paceSec.toString().padStart(2, '0')} /km`;
  }

  // Render map when workout data with route points is available
  $effect(() => {
    if (!workout?.route_points?.length || !mapContainer) return;

    // Dynamic import for Leaflet to avoid SSR issues
    import('leaflet').then((L) => {
      if (mapInstance) {
        mapInstance.remove();
      }

      // Import Leaflet CSS
      if (!document.querySelector('link[href*="leaflet.css"]')) {
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
        document.head.appendChild(link);
      }

      mapInstance = L.map(mapContainer, {
        attributionControl: true,
        zoomControl: true,
      });

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 19,
      }).addTo(mapInstance);

      const points: [number, number][] = workout!.route_points.map((p) => [p.latitude, p.longitude]);

      const polyline = L.polyline(points, {
        color: '#10b981',
        weight: 3,
        opacity: 0.9,
      }).addTo(mapInstance);

      // Start marker
      L.circleMarker(points[0], {
        radius: 6,
        color: '#22c55e',
        fillColor: '#22c55e',
        fillOpacity: 1,
      }).addTo(mapInstance).bindPopup('Start');

      // End marker
      L.circleMarker(points[points.length - 1], {
        radius: 6,
        color: '#ef4444',
        fillColor: '#ef4444',
        fillOpacity: 1,
      }).addTo(mapInstance).bindPopup('End');

      mapInstance.fitBounds(polyline.getBounds(), { padding: [30, 30] });
    });

    return () => {
      if (mapInstance) {
        mapInstance.remove();
        mapInstance = null;
      }
    };
  });
</script>

<div class="space-y-6">
  <!-- Back button -->
  <a
    href="/workouts"
    class="inline-flex items-center gap-2 text-sm text-surface-400 hover:text-surface-200 transition-colors"
    data-testid="workout-detail-back-link"
  >
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M10.5 19.5L3 12m0 0l7.5-7.5M3 12h18" />
    </svg>
    Back to Workouts
  </a>

  {#if loading}
    <div class="space-y-6">
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 animate-pulse">
        <div class="space-y-3">
          <div class="w-48 h-6 bg-surface-700 rounded"></div>
          <div class="w-32 h-4 bg-surface-700 rounded"></div>
        </div>
      </div>
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {#each Array(4) as _}
          <div class="bg-surface-800 rounded-xl border border-surface-700 p-4 animate-pulse">
            <div class="w-12 h-3 bg-surface-700 rounded mb-2"></div>
            <div class="w-16 h-6 bg-surface-700 rounded"></div>
          </div>
        {/each}
      </div>
    </div>
  {:else if error}
    <div class="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400">{error}</p>
      <button
        class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm transition-colors"
        onclick={loadWorkout}
      >
        Retry
      </button>
    </div>
  {:else if workout}
    <!-- Header -->
    <div class="bg-surface-800 rounded-xl border border-surface-700 p-6">
      <div class="flex items-center gap-4">
        <div class="w-12 h-12 rounded-xl bg-surface-700 flex items-center justify-center text-2xl">
          {getIcon(workout.activity_type)}
        </div>
        <div>
          <h1 class="text-xl font-bold text-surface-100">{getLabel(workout.activity_type)}</h1>
          <p class="text-sm text-surface-400 mt-0.5">
            {formatDate(workout.time, 'long')}
          </p>
        </div>
        <div class="ml-auto text-right">
          <p class="text-2xl font-bold text-surface-100">{formatDuration(workout.duration_sec)}</p>
          <p class="text-xs text-surface-500">Duration</p>
        </div>
      </div>
    </div>

    <!-- Stats row -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-4" data-testid="workout-stat-distance">
        <p class="text-xs text-surface-500 uppercase tracking-wider">Distance</p>
        <p class="text-lg font-semibold text-surface-100 mt-1">
          {workout.total_distance_m > 0 ? formatDistance(workout.total_distance_m) : '--'}
        </p>
      </div>
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-4" data-testid="workout-stat-energy">
        <p class="text-xs text-surface-500 uppercase tracking-wider">Energy</p>
        <p class="text-lg font-semibold text-surface-100 mt-1">
          {workout.total_energy_kj > 0 ? formatEnergy(workout.total_energy_kj) : '--'}
        </p>
      </div>
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-4" data-testid="workout-stat-pace">
        <p class="text-xs text-surface-500 uppercase tracking-wider">Avg Pace</p>
        <p class="text-lg font-semibold text-surface-100 mt-1">
          {calculatePace(workout.total_distance_m, workout.duration_sec)}
        </p>
      </div>
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-4" data-testid="workout-stat-duration">
        <p class="text-xs text-surface-500 uppercase tracking-wider">Duration</p>
        <p class="text-lg font-semibold text-surface-100 mt-1">
          {formatDuration(workout.duration_sec)}
        </p>
      </div>
    </div>

    <!-- Route map -->
    {#if workout.route_points && workout.route_points.length > 0}
      <div>
        <h3 class="text-sm font-semibold text-surface-300 mb-3">Route</h3>
        <div class="bg-surface-800 rounded-xl border border-surface-700 overflow-hidden" data-testid="workout-detail-map">
          <div bind:this={mapContainer} class="h-[400px] w-full"></div>
        </div>
      </div>
    {/if}

    <!-- Heart rate chart -->
    {#if hrData.length > 0}
      <div>
        <h3 class="text-sm font-semibold text-surface-300 mb-3">Heart Rate</h3>
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-4" style="height: 250px;">
          <TimeSeriesChart
            data={hrData}
            label="Heart Rate"
            color="#ef4444"
            fill={true}
          />
        </div>
      </div>
    {/if}

    <!-- Metadata -->
    {#if workout.metadata && Object.keys(workout.metadata).length > 0}
      <div>
        <h3 class="text-sm font-semibold text-surface-300 mb-3">Details</h3>
        <div class="bg-surface-800 rounded-xl border border-surface-700 divide-y divide-surface-700">
          {#each Object.entries(workout.metadata) as [key, value]}
            <div class="flex items-center justify-between px-4 py-3">
              <span class="text-sm text-surface-400">{key.replace(/([A-Z])/g, ' $1').trim()}</span>
              <span class="text-sm text-surface-200 font-medium">{value}</span>
            </div>
          {/each}
        </div>
      </div>
    {/if}
  {/if}
</div>
