<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    variant = 'panel',
    padded = true,
    href = undefined,
    class: klass = '',
    children,
    ...rest
  }: {
    variant?: 'panel' | 'flat' | 'outline';
    padded?: boolean;
    href?: string;
    class?: string;
    children?: Snippet;
    [k: string]: unknown;
  } = $props();

  const variants = {
    panel: 'bg-panel border border-edge',
    flat: 'bg-panel-2',
    outline: 'border border-edge',
  };

  const cls = $derived(`rounded-2xl ${variants[variant]} ${padded ? 'p-4' : ''} ${klass}`);
</script>

{#if href}
  <a {href} class="{cls} block transition-colors hover:border-edge-strong" {...rest}>
    {@render children?.()}
  </a>
{:else}
  <div class={cls} {...rest}>{@render children?.()}</div>
{/if}
