<script lang="ts" module>
  // The five one-tap reps-in-reserve buckets (CONTEXT.md "Effort"): "how many
  // more reps were left?". 4 is the open-ended "4+" floor. Tapping the selected
  // chip again clears it (Effort is always optional, never required).
  export const RIR_CHIPS: { value: number; label: string }[] = [
    { value: 0, label: '0' },
    { value: 1, label: '1' },
    { value: 2, label: '2' },
    { value: 3, label: '3' },
    { value: 4, label: '4+' },
  ];
</script>

<script lang="ts">
  let {
    value = null,
    nudge = false,
    onchange,
  }: {
    value?: number | null;
    /** Highlight the control to nudge for Effort (the Exercise's last Set). */
    nudge?: boolean;
    onchange: (v: number | null) => void;
  } = $props();

  function tap(v: number) {
    // Tapping the current value clears it; never blocks.
    onchange(value === v ? null : v);
  }
</script>

<div class="flex items-center gap-1.5">
  <span class="text-[0.65rem] uppercase tracking-wide font-medium {nudge && value === null ? 'text-primary-300' : 'text-surface-500'}">
    {nudge && value === null ? 'Effort?' : 'RIR'}
  </span>
  <div class="flex gap-1 {nudge && value === null ? 'ring-1 ring-primary-500/40 rounded-lg p-0.5' : ''}">
    {#each RIR_CHIPS as chip}
      <button
        onclick={() => tap(chip.value)}
        class="min-w-[1.85rem] h-7 px-1.5 rounded-md text-xs font-semibold border transition-colors
               {value === chip.value
                 ? 'bg-primary-500 text-white border-primary-500'
                 : 'bg-surface-800 text-surface-400 border-surface-700 hover:border-surface-500'}"
        aria-label="{chip.label} reps in reserve"
        aria-pressed={value === chip.value}
      >
        {chip.label}
      </button>
    {/each}
  </div>
</div>
