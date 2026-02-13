<script lang="ts">
  import Sparkline from '$lib/components/charts/Sparkline.svelte';

  interface Props {
    title: string;
    value: number | string | null;
    unit: string;
    trend?: number | null;
    sparklineData?: number[];
    color?: string;
    icon: string;
  }

  let {
    title,
    value,
    unit,
    trend = null,
    sparklineData = [],
    color = '#10b981',
    icon,
  }: Props = $props();

  let formattedValue = $derived(
    value === null || value === undefined
      ? '--'
      : typeof value === 'number'
        ? value.toLocaleString()
        : value
  );

  let trendColor = $derived(
    trend === null || trend === undefined
      ? ''
      : trend > 0
        ? 'text-green-400'
        : trend < 0
          ? 'text-red-400'
          : 'text-surface-400'
  );

  let trendIcon = $derived(
    trend === null || trend === undefined
      ? ''
      : trend > 0
        ? 'M5 15l7-7 7 7'
        : trend < 0
          ? 'M19 9l-7 7-7-7'
          : 'M5 12h14'
  );
</script>

<div class="rounded-xl bg-surface-800 p-4 flex flex-col gap-3 border border-surface-700/50 hover:border-surface-600/50 transition-colors" data-testid="metric-card-{title}">
  <!-- Header row: icon + title -->
  <div class="flex items-center gap-2">
    <div
      class="w-8 h-8 rounded-lg flex items-center justify-center"
      style="background-color: {color}22;"
    >
      <svg class="w-4 h-4" fill="none" stroke={color} viewBox="0 0 24 24" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d={icon} />
      </svg>
    </div>
    <span class="text-sm text-surface-400 font-medium">{title}</span>
  </div>

  <!-- Value row -->
  <div class="flex items-baseline gap-1.5">
    <span class="text-2xl font-bold text-surface-100" data-testid="metric-value-{title}">{formattedValue}</span>
    <span class="text-sm text-surface-500">{unit}</span>

    {#if trend !== null && trend !== undefined}
      <div class="flex items-center gap-0.5 ml-auto {trendColor}">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d={trendIcon} />
        </svg>
        <span class="text-xs font-medium">{Math.abs(trend).toFixed(1)}%</span>
      </div>
    {/if}
  </div>

  <!-- Sparkline -->
  {#if sparklineData.length > 1}
    <div class="mt-auto pt-1">
      <Sparkline data={sparklineData} {color} width={200} height={28} />
    </div>
  {/if}
</div>
