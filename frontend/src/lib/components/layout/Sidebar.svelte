<script lang="ts">
  import { page } from '$app/stores';
  import { MORE_GROUPS, PRIMARY_TABS, isActive, tabIsActive } from '$lib/nav';
  import { PRODUCT_NAME, PRODUCT_TAGLINE } from '$lib/brand';

  // Desktop adaptation of the phone-first nav: the same five primary
  // destinations as the bottom bar, with the "More" groups expanded inline.
  let { onNavigate }: { onNavigate?: () => void } = $props();
  const pathname = $derived($page.url.pathname);
</script>

<aside class="flex h-full w-64 flex-col border-r border-edge bg-panel">
  <a href="/" onclick={onNavigate} class="flex items-center gap-3 px-5 py-5">
    <div class="grid h-9 w-9 place-items-center rounded-xl bg-accent text-on-accent">
      <svg class="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
        <path d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
      </svg>
    </div>
    <div class="leading-tight">
      <div class="text-sm font-semibold tracking-tight text-ink">{PRODUCT_NAME}</div>
      {#if PRODUCT_TAGLINE}<div class="text-[0.7rem] text-ink-3">{PRODUCT_TAGLINE}</div>{/if}
    </div>
  </a>

  <nav class="flex-1 overflow-y-auto px-3 py-2">
    <div class="space-y-1">
      {#each PRIMARY_TABS as tab (tab.href)}
        {@const active = tabIsActive(tab, pathname)}
        <a
          href={tab.href}
          onclick={onNavigate}
          class="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors {active
            ? 'bg-accent-soft text-accent-ink'
            : 'text-ink-2 hover:bg-panel-2 hover:text-ink'}"
        >
          <svg
            class="h-5 w-5 flex-shrink-0"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            stroke-width={active ? 2 : 1.6}
          >
            <path stroke-linecap="round" stroke-linejoin="round" d={tab.icon} />
          </svg>
          <span>{tab.label}</span>
          {#if active}<span class="ml-auto h-1.5 w-1.5 rounded-full bg-accent"></span>{/if}
        </a>
      {/each}
    </div>

    {#each MORE_GROUPS as group (group.title)}
      <div class="mt-6">
        <h3 class="px-3 pb-1.5 text-[0.68rem] font-semibold uppercase tracking-[0.14em] text-ink-3">
          {group.title}
        </h3>
        <div class="space-y-0.5">
          {#each group.items as item (item.href)}
            {@const active = isActive(item.href, pathname)}
            <a
              href={item.href}
              onclick={onNavigate}
              class="flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors {active
                ? 'text-accent-ink'
                : 'text-ink-3 hover:bg-panel-2 hover:text-ink'}"
            >
              <svg
                class="h-[18px] w-[18px] flex-shrink-0"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                stroke-width="1.5"
              >
                <path stroke-linecap="round" stroke-linejoin="round" d={item.icon} />
              </svg>
              <span>{item.label}</span>
            </a>
          {/each}
        </div>
      </div>
    {/each}
  </nav>

  <div class="border-t border-edge px-4 py-3">
    <p class="text-center text-[0.7rem] text-ink-3">v1.0.0</p>
  </div>
</aside>
