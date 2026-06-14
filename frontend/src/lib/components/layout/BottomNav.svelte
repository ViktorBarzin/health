<script lang="ts">
  import { page } from '$app/stores';
  import {
    MORE_GROUPS,
    MORE_ICON,
    PRIMARY_TABS,
    isActive,
    isMoreActive,
    tabIsActive,
  } from '$lib/nav';
  import BottomSheet from '$lib/components/ui/BottomSheet.svelte';
  import { haptic } from '$lib/ui/haptics';

  // Phone-first primary navigation (ADR-0007): a fixed bottom tab bar in the
  // thumb zone for one-handed use at the rack. Four route tabs + a "More" sheet
  // keep every page reachable; hidden on lg+ where the Sidebar takes over.
  let moreOpen = $state(false);
  const pathname = $derived($page.url.pathname);
  const moreActive = $derived(isMoreActive(pathname));
</script>

<nav
  class="fixed inset-x-0 bottom-0 z-30 border-t border-edge bg-panel/90 backdrop-blur-xl pb-[env(safe-area-inset-bottom)] lg:hidden"
  aria-label="Primary"
>
  <div class="grid grid-cols-5">
    {#each PRIMARY_TABS as tab (tab.href)}
      {@const active = tabIsActive(tab, pathname)}
      <a
        href={tab.href}
        onclick={() => haptic('select')}
        aria-current={active ? 'page' : undefined}
        class="relative flex flex-col items-center justify-center gap-1 py-2.5 transition-colors duration-150 {active
          ? 'text-accent-ink'
          : 'text-ink-3'}"
      >
        {#if active}<span class="absolute top-0 h-0.5 w-8 rounded-full bg-accent"></span>{/if}
        <svg
          class="h-6 w-6"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
          stroke-width={active ? 2 : 1.6}
        >
          <path stroke-linecap="round" stroke-linejoin="round" d={tab.icon} />
        </svg>
        <span class="text-[0.65rem] font-medium tracking-wide">{tab.label}</span>
      </a>
    {/each}

    <button
      onclick={() => {
        haptic('select');
        moreOpen = true;
      }}
      aria-expanded={moreOpen}
      aria-label="More"
      class="relative flex flex-col items-center justify-center gap-1 py-2.5 transition-colors duration-150 {moreActive ||
      moreOpen
        ? 'text-accent-ink'
        : 'text-ink-3'}"
    >
      {#if moreActive}<span class="absolute top-0 h-0.5 w-8 rounded-full bg-accent"></span>{/if}
      <svg class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.8">
        <path stroke-linecap="round" stroke-linejoin="round" d={MORE_ICON} />
      </svg>
      <span class="text-[0.65rem] font-medium tracking-wide">More</span>
    </button>
  </div>
</nav>

<BottomSheet bind:open={moreOpen} title="More">
  <div class="space-y-5 pb-2">
    {#each MORE_GROUPS as group (group.title)}
      <div>
        <h3 class="px-1 pb-2 text-[0.7rem] font-semibold uppercase tracking-[0.14em] text-ink-3">
          {group.title}
        </h3>
        <div class="grid grid-cols-3 gap-2">
          {#each group.items as item (item.href)}
            {@const active = isActive(item.href, pathname)}
            <a
              href={item.href}
              onclick={() => {
                haptic('select');
                moreOpen = false;
              }}
              class="flex flex-col items-center gap-2 rounded-2xl border px-2 py-4 text-center transition-colors {active
                ? 'border-accent bg-accent-soft text-accent-ink'
                : 'border-edge bg-panel-2 text-ink-2 hover:text-ink'}"
            >
              <svg
                class="h-6 w-6"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                stroke-width="1.6"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d={item.icon} />
              </svg>
              <span class="text-xs font-medium">{item.label}</span>
            </a>
          {/each}
        </div>
      </div>
    {/each}
  </div>
</BottomSheet>
