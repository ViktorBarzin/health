<script lang="ts">
  import { page } from '$app/stores';

  interface Props {
    onNavigate?: () => void;
  }

  let { onNavigate }: Props = $props();

  const navItems = [
    { href: '/', label: 'Dashboard', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
    { href: '/metrics', label: 'Metrics', icon: 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z' },
    { href: '/workouts', label: 'Workouts', icon: 'M13 10V3L4 14h7v7l9-11h-7z' },
    { href: '/sleep', label: 'Sleep', icon: 'M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z' },
    { href: '/body', label: 'Body', icon: 'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z' },
    { href: '/trends', label: 'Trends', icon: 'M13 7h8m0 0v8m0-8l-8 8-4-4-6 6' },
    { href: '/settings', label: 'Settings', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
  ];

  function isActive(href: string, pathname: string): boolean {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href);
  }
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
    {#each navItems as item}
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
