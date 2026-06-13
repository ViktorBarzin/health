<script lang="ts">
  import { page } from '$app/stores';
  import { NAV_ITEMS, isActive } from '$lib/nav';

  interface Props {
    onNavigate?: () => void;
  }

  let { onNavigate }: Props = $props();
</script>

<aside class="w-64 h-full bg-surface-900 border-r border-surface-700 flex flex-col">
  <!-- Logo / Brand -->
  <div class="flex items-center gap-3 px-6 py-5 border-b border-surface-700">
    <div class="w-8 h-8 rounded-lg bg-primary-500 flex items-center justify-center">
      <svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" />
      </svg>
    </div>
    <div>
      <h1 class="text-sm font-semibold text-surface-100">Health Dashboard</h1>
      <p class="text-xs text-surface-500">Apple Health Data</p>
    </div>
  </div>

  <!-- Navigation -->
  <nav class="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
    {#each NAV_ITEMS as item}
      {@const active = isActive(item.href, $page.url.pathname)}
      <a
        href={item.href}
        onclick={onNavigate}
        class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors
               {active
                 ? 'bg-primary-500/15 text-primary-400'
                 : 'text-surface-400 hover:bg-surface-800 hover:text-surface-200'}"
      >
        <svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d={item.icon} />
        </svg>
        <span>{item.label}</span>
        {#if active}
          <div class="ml-auto w-1.5 h-1.5 rounded-full bg-primary-400"></div>
        {/if}
      </a>
    {/each}
  </nav>

  <!-- Bottom section -->
  <div class="px-4 py-3 border-t border-surface-700">
    <p class="text-xs text-surface-600 text-center">v1.0.0</p>
  </div>
</aside>
