<script lang="ts">
  // The hero number, instrument-style: big mono tabular figures, a quieter
  // fraction, a small unit and an optional label/sub. The screen's focal point.

  let {
    value,
    unit = undefined,
    label = undefined,
    sub = undefined,
    size = 'lg',
    accent = false,
  }: {
    value: number | string;
    unit?: string;
    label?: string;
    sub?: string;
    size?: 'md' | 'lg' | 'xl';
    accent?: boolean;
  } = $props();

  function split(v: number | string): { whole: string; frac: string } {
    if (typeof v === 'string') return { whole: v, frac: '' };
    const fixed = Number.isInteger(v) ? String(v) : String(Math.round(v * 100) / 100);
    const [whole, frac] = fixed.split('.');
    return { whole, frac: frac ? '.' + frac : '' };
  }

  const parts = $derived(split(value));
  const sizes = { md: 'text-2xl', lg: 'text-4xl', xl: 'text-6xl' };
</script>

<div class="flex flex-col">
  {#if label}
    <span class="mb-1 text-[0.7rem] font-medium uppercase tracking-[0.14em] text-ink-3">{label}</span>
  {/if}
  <span class="readout font-semibold leading-none {sizes[size]} {accent ? 'text-accent-ink' : 'text-ink'}">
    <span>{parts.whole}</span>{#if parts.frac}<span class="text-ink-3">{parts.frac}</span>{/if}{#if unit}<span
        class="ml-1.5 text-[0.4em] font-semibold uppercase tracking-wide text-ink-3">{unit}</span
      >{/if}
  </span>
  {#if sub}<span class="mt-1.5 text-xs text-ink-2">{sub}</span>{/if}
</div>
