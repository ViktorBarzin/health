<script lang="ts">
  import { dateRange, type Preset, type Resolution } from '$lib/stores/date-range.svelte';

  const presets: { value: Preset; label: string }[] = [
    { value: '7d', label: '7D' },
    { value: '30d', label: '30D' },
    { value: '90d', label: '90D' },
    { value: '1y', label: '1Y' },
    { value: 'all', label: 'All' },
  ];

  const resolutions: { value: Resolution; label: string }[] = [
    { value: 'raw', label: 'Raw' },
    { value: 'day', label: 'Day' },
    { value: 'week', label: 'Week' },
    { value: 'month', label: 'Month' },
  ];

  function handleStartChange(e: Event) {
    const target = e.target as HTMLInputElement;
    dateRange.setRange(new Date(target.value), dateRange.end);
  }

  function handleEndChange(e: Event) {
    const target = e.target as HTMLInputElement;
    dateRange.setRange(dateRange.start, new Date(target.value));
  }
</script>

<div class="flex flex-wrap items-center gap-2">
  <!-- Preset buttons -->
  <div class="flex items-center rounded-lg bg-surface-800 p-0.5">
    {#each presets as preset}
      <button
        class="px-2.5 py-1 text-xs font-medium rounded-md transition-colors
               {dateRange.activePreset === preset.value
                 ? 'bg-primary-500 text-white'
                 : 'text-surface-400 hover:text-surface-200'}"
        onclick={() => dateRange.setPreset(preset.value)}
      >
        {preset.label}
      </button>
    {/each}
  </div>

  <!-- Custom date inputs -->
  <div class="flex items-center gap-1.5">
    <input
      type="date"
      value={dateRange.startISO}
      onchange={handleStartChange}
      class="bg-surface-800 text-surface-300 text-xs rounded-md border border-surface-700
             px-2 py-1 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
    />
    <span class="text-surface-500 text-xs">to</span>
    <input
      type="date"
      value={dateRange.endISO}
      onchange={handleEndChange}
      class="bg-surface-800 text-surface-300 text-xs rounded-md border border-surface-700
             px-2 py-1 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
    />
  </div>

  <!-- Resolution toggle -->
  <div class="flex items-center rounded-lg bg-surface-800 p-0.5">
    {#each resolutions as res}
      <button
        class="px-2 py-1 text-xs font-medium rounded-md transition-colors
               {dateRange.resolution === res.value
                 ? 'bg-accent-600 text-white'
                 : 'text-surface-400 hover:text-surface-200'}"
        onclick={() => dateRange.setResolution(res.value)}
      >
        {res.label}
      </button>
    {/each}
  </div>
</div>
