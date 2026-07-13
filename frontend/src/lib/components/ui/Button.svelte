<script lang="ts">
  import type { Snippet } from 'svelte';
  import { haptic, type HapticKind } from '$lib/ui/haptics';

  type Variant = 'accent' | 'solid' | 'outline' | 'ghost' | 'danger';
  type Size = 'sm' | 'md' | 'lg';

  let {
    variant = 'accent',
    size = 'md',
    href = undefined,
    type = 'button',
    disabled = false,
    full = false,
    feedback = 'select',
    onclick = undefined,
    children,
    ...rest
  }: {
    variant?: Variant;
    size?: Size;
    href?: string;
    type?: 'button' | 'submit' | 'reset';
    disabled?: boolean;
    full?: boolean;
    feedback?: HapticKind | null;
    onclick?: (e: MouseEvent) => void;
    children?: Snippet;
    [k: string]: unknown;
  } = $props();

  const sizes: Record<Size, string> = {
    sm: 'h-9 px-3.5 text-sm gap-1.5 rounded-lg',
    md: 'h-11 px-4 text-sm gap-2 rounded-xl',
    lg: 'h-14 px-6 text-base gap-2.5 rounded-2xl',
  };
  const variants: Record<Variant, string> = {
    accent: 'bg-accent font-semibold hover:bg-accent-strong',
    solid: 'bg-panel-2 text-ink hover:bg-elevated',
    outline: 'border border-edge-strong text-ink hover:bg-panel-2',
    ghost: 'text-ink-2 hover:bg-panel-2 hover:text-ink',
    danger: 'bg-danger/15 text-danger hover:bg-danger/25',
  };

  function handle(e: MouseEvent) {
    if (disabled) return;
    if (feedback) haptic(feedback);
    onclick?.(e);
  }

  const cls = $derived(
    `inline-flex items-center justify-center font-medium select-none transition-[transform,background-color,color] duration-150 active:scale-[0.97] ${sizes[size]} ${variants[variant]} ${full ? 'w-full' : ''}`,
  );
</script>

{#if href}
  <a {href} class={cls} onclick={handle} {...rest}>{@render children?.()}</a>
{:else}
  <button
    {type}
    {disabled}
    class="{cls} disabled:opacity-40 disabled:pointer-events-none"
    onclick={handle}
    {...rest}>{@render children?.()}</button>
{/if}
