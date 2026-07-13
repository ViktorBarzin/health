<script lang="ts">
  import type { Snippet } from 'svelte';
  import { haptic } from '$lib/ui/haptics';

  let {
    selected = false,
    size = 'md',
    onclick = undefined,
    children,
    ...rest
  }: {
    selected?: boolean;
    size?: 'sm' | 'md';
    onclick?: (e: MouseEvent) => void;
    children?: Snippet;
    [k: string]: unknown;
  } = $props();

  const sizes = { sm: 'h-8 px-3 text-xs', md: 'h-10 px-4 text-sm' };

  function handle(e: MouseEvent) {
    haptic('select');
    onclick?.(e);
  }
</script>

<button
  type="button"
  aria-pressed={selected}
  onclick={handle}
  class="inline-flex items-center justify-center font-medium rounded-full border transition-[transform,background-color,color,border-color] duration-150 active:scale-95 {sizes[
    size
  ]} {selected
    ? 'bg-accent-soft border-accent text-accent-ink'
    : 'bg-panel-2 border-edge text-ink-2 hover:text-ink'}"
  {...rest}>{@render children?.()}</button>
