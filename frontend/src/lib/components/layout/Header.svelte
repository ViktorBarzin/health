<script lang="ts">
  import { auth } from '$lib/stores/auth.svelte';
  import DateRangePicker from './DateRangePicker.svelte';

  interface Props {
    title: string;
    onToggleSidebar?: () => void;
  }

  let { title, onToggleSidebar }: Props = $props();

  let userMenuOpen = $state(false);

  function toggleUserMenu() {
    userMenuOpen = !userMenuOpen;
  }

  function closeUserMenu() {
    userMenuOpen = false;
  }

  async function handleLogout() {
    closeUserMenu();
    await auth.logout();
  }
</script>

<header class="bg-surface-900 border-b border-surface-700 px-4 lg:px-6 py-3">
  <div class="flex items-center justify-between gap-4">
    <!-- Left: hamburger + title -->
    <div class="flex items-center gap-3">
      <button
        class="lg:hidden p-1.5 rounded-lg text-surface-400 hover:bg-surface-800 hover:text-surface-200 transition-colors"
        onclick={onToggleSidebar}
        aria-label="Toggle sidebar"
        data-testid="header-menu-toggle"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
        </svg>
      </button>
      <h2 class="text-lg font-semibold text-surface-100">{title}</h2>
    </div>

    <!-- Center: date range picker -->
    <div class="hidden md:flex flex-1 justify-center max-w-2xl">
      <DateRangePicker />
    </div>

    <!-- Right: user menu -->
    <div class="relative">
      <button
        class="flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm text-surface-400 hover:bg-surface-800 hover:text-surface-200 transition-colors"
        onclick={toggleUserMenu}
        data-testid="header-user-menu-btn"
      >
        <div class="w-7 h-7 rounded-full bg-primary-500/20 flex items-center justify-center">
          <span class="text-xs font-medium text-primary-400">
            {auth.user?.email?.charAt(0).toUpperCase() ?? '?'}
          </span>
        </div>
        <span class="hidden sm:inline">{auth.user?.email ?? ''}</span>
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
        </svg>
      </button>

      {#if userMenuOpen}
        <button class="fixed inset-0 z-40" onclick={closeUserMenu} aria-label="Close menu"></button>
        <div class="absolute right-0 mt-2 w-48 bg-surface-800 rounded-lg shadow-lg border border-surface-700 py-1 z-50">
          <div class="px-4 py-2 border-b border-surface-700">
            <p class="text-sm text-surface-200 truncate">{auth.user?.email}</p>
            <p class="text-xs text-surface-500">Logged in</p>
          </div>
          <a
            href="/settings"
            class="block px-4 py-2 text-sm text-surface-300 hover:bg-surface-700 hover:text-surface-100 transition-colors"
            onclick={closeUserMenu}
          >
            Settings
          </a>
          <button
            class="w-full text-left px-4 py-2 text-sm text-red-400 hover:bg-surface-700 transition-colors"
            onclick={handleLogout}
            data-testid="header-logout-btn"
          >
            Log out
          </button>
        </div>
      {/if}
    </div>
  </div>

  <!-- Mobile date range picker -->
  <div class="md:hidden mt-3">
    <DateRangePicker />
  </div>
</header>
