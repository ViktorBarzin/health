<script lang="ts">
  import type { Snippet } from 'svelte';
  import { fade, fly } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';

  let {
    open = $bindable(false),
    title = undefined,
    label = 'Dialog',
    onclose = undefined,
    children,
  }: {
    open?: boolean;
    title?: string;
    label?: string;
    onclose?: () => void;
    children?: Snippet;
  } = $props();

  function close() {
    open = false;
    onclose?.();
  }

  function onkeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') close();
  }
</script>

<svelte:window onkeydown={open ? onkeydown : undefined} />

{#if open}
  <button
    class="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
    transition:fade={{ duration: 150 }}
    onclick={close}
    aria-label="Close"
  ></button>
  <div
    class="fixed inset-x-0 bottom-0 z-50 mx-auto max-w-lg max-h-[85vh] overflow-y-auto rounded-t-3xl
           border-t border-edge bg-panel shadow-2xl pb-[max(1rem,env(safe-area-inset-bottom))]"
    transition:fly={{ y: 340, duration: 260, easing: cubicOut }}
    role="dialog"
    aria-modal="true"
    aria-label={title ?? label}
  >
    <div class="mx-auto mt-3 mb-1 h-1.5 w-11 rounded-full bg-edge-strong"></div>
    {#if title}
      <div class="px-5 pt-2 pb-1">
        <h2 class="text-lg font-semibold tracking-tight text-ink">{title}</h2>
      </div>
    {/if}
    <div class="px-4 pt-2">{@render children?.()}</div>
  </div>
{/if}
