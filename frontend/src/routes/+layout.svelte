<script lang="ts">
  import '../app.css';
  import { auth } from '$lib/stores/auth.svelte';
  import { page } from '$app/stores';
  import Sidebar from '$lib/components/layout/Sidebar.svelte';
  import Header from '$lib/components/layout/Header.svelte';

  let { children } = $props();

  let sidebarOpen = $state(false);

  function toggleSidebar() {
    sidebarOpen = !sidebarOpen;
  }

  function closeSidebar() {
    sidebarOpen = false;
  }

  // Identity is established at the edge by Authentik forward-auth (ADR-0003);
  // there is no in-app login. We just resolve who the backend sees.
  $effect(() => {
    auth.checkAuth();
  });

  let pageTitle = $derived(() => {
    const path = $page.url.pathname;
    if (path === '/') return 'Dashboard';
    if (path.startsWith('/metrics')) return 'Metrics';
    if (path.startsWith('/workouts')) return 'Workouts';
    if (path.startsWith('/sleep')) return 'Sleep';
    if (path.startsWith('/body')) return 'Body';
    if (path.startsWith('/trends')) return 'Trends';
    if (path.startsWith('/settings')) return 'Settings';
    return 'Health Dashboard';
  });
</script>

{#if auth.loading}
  <div class="flex items-center justify-center min-h-screen bg-surface-950">
    <div class="flex flex-col items-center gap-4">
      <div class="w-10 h-10 border-3 border-primary-500 border-t-transparent rounded-full animate-spin"></div>
      <p class="text-surface-400 text-sm">Loading...</p>
    </div>
  </div>
{:else if auth.user}
  <div class="flex h-screen overflow-hidden bg-surface-950">
    <!-- Mobile overlay -->
    {#if sidebarOpen}
      <button
        class="fixed inset-0 bg-black/50 z-30 lg:hidden"
        onclick={closeSidebar}
        aria-label="Close sidebar"
      ></button>
    {/if}

    <!-- Sidebar -->
    <div
      class="fixed lg:static inset-y-0 left-0 z-40 transition-sidebar
             {sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}"
    >
      <Sidebar onNavigate={closeSidebar} />
    </div>

    <!-- Main content -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <Header title={pageTitle()} onToggleSidebar={toggleSidebar} />
      <main class="flex-1 overflow-y-auto p-4 lg:p-6">
        {@render children()}
      </main>
    </div>
  </div>
{:else}
  <!-- Behind Authentik forward-auth this is unreachable; locally it means no
       identity header and no DEV_AUTH_EMAIL set. -->
  <div class="flex items-center justify-center min-h-screen bg-surface-950 px-4">
    <div class="text-center">
      <h1 class="text-xl font-semibold text-surface-100">Not signed in</h1>
      <p class="text-sm text-surface-500 mt-2">
        This app is protected by single sign-on. Sign in through your identity provider to continue.
      </p>
    </div>
  </div>
{/if}
