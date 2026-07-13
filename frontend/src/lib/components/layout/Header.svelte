<script lang="ts">
  import { auth } from '$lib/stores/auth.svelte';

  // The global date-range picker no longer lives in the shell (ADR-0008) — it
  // belongs only on the Progress review screens, where a range is meaningful.
  let { title }: { title: string } = $props();
  let userMenuOpen = $state(false);
</script>

<header
  class="sticky top-0 z-20 border-b border-edge bg-panel/85 px-4 py-3 pt-[max(0.75rem,env(safe-area-inset-top))] backdrop-blur-xl lg:px-6"
>
  <div class="flex items-center justify-between gap-4">
    <div class="flex min-w-0 items-center gap-2.5">
      <div
        class="grid h-7 w-7 flex-shrink-0 place-items-center rounded-lg bg-accent text-on-accent lg:hidden"
      >
        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="currentColor">
          <path d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
        </svg>
      </div>
      <h1 class="truncate text-lg font-semibold tracking-tight text-ink">{title}</h1>
    </div>

    <div class="relative flex-shrink-0">
      <button
        onclick={() => (userMenuOpen = !userMenuOpen)}
        class="flex items-center rounded-full p-0.5 transition-colors hover:bg-panel-2"
        aria-label="Account"
      >
        <span
          class="grid h-8 w-8 place-items-center rounded-full bg-accent-soft text-xs font-semibold text-accent-ink"
        >
          {auth.user?.email?.charAt(0).toUpperCase() ?? '?'}
        </span>
      </button>

      {#if userMenuOpen}
        <button
          class="fixed inset-0 z-40"
          onclick={() => (userMenuOpen = false)}
          aria-label="Close menu"
        ></button>
        <div
          class="absolute right-0 z-50 mt-2 w-56 overflow-hidden rounded-2xl border border-edge bg-panel shadow-xl"
        >
          <div class="border-b border-edge px-4 py-3">
            <p class="truncate text-sm text-ink">{auth.user?.email}</p>
            <p class="text-xs text-ink-3">Signed in</p>
          </div>
          <a
            href="/settings"
            onclick={() => (userMenuOpen = false)}
            class="block px-4 py-2.5 text-sm text-ink-2 transition-colors hover:bg-panel-2 hover:text-ink"
            >Settings</a
          >
        </div>
      {/if}
    </div>
  </div>
</header>
