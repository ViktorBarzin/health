<script lang="ts">
  import { page } from '$app/stores';
  import {
    MOBILE_OVERFLOW,
    MOBILE_PRIMARY,
    isActive,
    isOverflowActive,
  } from '$lib/nav';

  // Phone-first primary navigation (ADR-0007): a fixed bottom tab bar that sits
  // in the thumb zone for one-handed use at a gym rack. Hidden on lg+ where the
  // desktop Sidebar takes over. Pinned tabs + a "More" sheet keep every page
  // reachable.
  let moreOpen = $state(false);

  const pathname = $derived($page.url.pathname);
  const overflowActive = $derived(isOverflowActive(pathname));

  function closeMore() {
    moreOpen = false;
  }
</script>

<!-- Overflow sheet -->
{#if moreOpen}
  <button
    class="fixed inset-0 bg-black/60 z-40 lg:hidden"
    onclick={closeMore}
    aria-label="Close menu"
  ></button>
  <div
    class="fixed bottom-0 inset-x-0 z-50 lg:hidden bg-surface-900 border-t border-surface-700
           rounded-t-2xl pb-[env(safe-area-inset-bottom)] shadow-2xl"
    role="dialog"
    aria-label="More navigation"
  >
    <div class="mx-auto my-2 h-1 w-10 rounded-full bg-surface-600"></div>
    <nav class="grid grid-cols-3 gap-1 p-3">
      {#each MOBILE_OVERFLOW as item}
        {@const active = isActive(item.href, pathname)}
        <a
          href={item.href}
          onclick={closeMore}
          class="flex flex-col items-center gap-1.5 rounded-xl py-3 text-xs font-medium transition-colors
                 {active
                   ? 'bg-primary-500/15 text-primary-400'
                   : 'text-surface-400 hover:bg-surface-800 hover:text-surface-200'}"
        >
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d={item.icon} />
          </svg>
          <span>{item.label}</span>
        </a>
      {/each}
    </nav>
  </div>
{/if}

<!-- Bottom tab bar -->
<nav
  class="fixed bottom-0 inset-x-0 z-30 lg:hidden bg-surface-900/95 backdrop-blur border-t border-surface-700
         pb-[env(safe-area-inset-bottom)]"
  aria-label="Primary"
>
  <div class="grid grid-cols-5">
    {#each MOBILE_PRIMARY as item}
      {@const active = isActive(item.href, pathname)}
      <a
        href={item.href}
        class="flex flex-col items-center justify-center gap-0.5 py-2 text-[0.65rem] font-medium transition-colors
               {active ? 'text-primary-400' : 'text-surface-400 hover:text-surface-200'}"
        aria-current={active ? 'page' : undefined}
      >
        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.75">
          <path stroke-linecap="round" stroke-linejoin="round" d={item.icon} />
        </svg>
        <span>{item.label}</span>
      </a>
    {/each}

    <!-- More -->
    <button
      onclick={() => (moreOpen = !moreOpen)}
      class="flex flex-col items-center justify-center gap-0.5 py-2 text-[0.65rem] font-medium transition-colors
             {overflowActive || moreOpen ? 'text-primary-400' : 'text-surface-400 hover:text-surface-200'}"
      aria-expanded={moreOpen}
      aria-label="More"
    >
      <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.75">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
      </svg>
      <span>More</span>
    </button>
  </div>
</nav>
