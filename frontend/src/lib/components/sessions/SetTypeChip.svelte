<script lang="ts" module>
  import type { SetType } from '$lib/types';

  // The four set types and their compact chip styling. Non-normal types are
  // excluded from volume/PR stats (CONTEXT.md) — the muted styling hints that
  // they "don't count" without spelling it out at the rack.
  export const SET_TYPES: { value: SetType; short: string; label: string }[] = [
    { value: 'normal', short: 'N', label: 'Normal' },
    { value: 'warmup', short: 'W', label: 'Warmup' },
    { value: 'drop', short: 'D', label: 'Drop' },
    { value: 'failure', short: 'F', label: 'Failure' },
  ];
</script>

<script lang="ts">
  let {
    value,
    onchange,
  }: { value: SetType; onchange: (v: SetType) => void } = $props();

  let open = $state(false);

  const styles: Record<SetType, string> = {
    normal: 'bg-surface-700 text-surface-200 border-surface-600',
    warmup: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    drop: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
    failure: 'bg-red-500/15 text-red-300 border-red-500/30',
  };

  function select(v: SetType) {
    open = false;
    onchange(v);
  }
</script>

<div class="relative">
  <button
    onclick={() => (open = !open)}
    class="w-8 h-8 rounded-lg border text-xs font-bold transition-colors {styles[value]}"
    aria-label="Set type: {value}"
    aria-haspopup="true"
    aria-expanded={open}
  >
    {SET_TYPES.find((t) => t.value === value)?.short}
  </button>
  {#if open}
    <button class="fixed inset-0 z-40" onclick={() => (open = false)} aria-label="Close set type"></button>
    <div class="absolute z-50 top-9 left-0 bg-surface-800 border border-surface-700 rounded-lg shadow-xl p-1 w-32">
      {#each SET_TYPES as t}
        <button
          onclick={() => select(t.value)}
          class="w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-left text-sm
                 hover:bg-surface-700 transition-colors {value === t.value ? 'text-primary-300' : 'text-surface-300'}"
        >
          <span class="w-5 h-5 rounded border text-[0.6rem] font-bold flex items-center justify-center {styles[t.value]}">{t.short}</span>
          {t.label}
        </button>
      {/each}
    </div>
  {/if}
</div>
