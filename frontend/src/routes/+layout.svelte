<script lang="ts">
  import '../app.css';
  // Self-hosted Geist (ADR-0008): variable woff2 bundled by Vite, cached by the
  // service worker — no CDN, works offline.
  import '@fontsource-variable/geist';
  import '@fontsource-variable/geist-mono';

  import { auth } from '$lib/stores/auth.svelte';
  import { initSyncEngine } from '$lib/sync/engine';
  import { initTheme } from '$lib/ui/theme';
  import { PRODUCT_NAME } from '$lib/brand';
  import { page } from '$app/stores';
  import Sidebar from '$lib/components/layout/Sidebar.svelte';
  import Header from '$lib/components/layout/Header.svelte';
  import BottomNav from '$lib/components/layout/BottomNav.svelte';
  // PWA web-manifest link (ADR-0007): pwaInfo carries the hashed manifest
  // filename; we inject its <link> rather than hardcoding the path.
  import { pwaInfo } from 'virtual:pwa-info';

  let { children } = $props();

  const webManifestLink = $derived(pwaInfo ? pwaInfo.webManifest.linkTag : '');

  // Restore any explicit light/dark override on boot (auto-follow is pure CSS).
  $effect(() => {
    initTheme();
  });

  // Identity is established at the edge by Authentik forward-auth (ADR-0003).
  $effect(() => {
    auth.checkAuth();
  });

  // Bring the offline-sync engine up on load (ADR-0005, #6).
  $effect(() => {
    void initSyncEngine();
  });

  const TITLES: Record<string, string> = {
    '/': 'Today',
    '/sessions': 'Train',
    '/nutrition': 'Nutrition',
    '/progress': 'Progress',
    '/programs': 'Programs',
    '/exercises': 'Exercises',
    '/workouts': 'Workouts',
    '/metrics': 'Metrics',
    '/trends': 'Trends',
    '/body': 'Body',
    '/sleep': 'Sleep',
    '/analytics': 'Analytics',
    '/principles': 'Principle',
    '/settings': 'Settings',
  };

  const pageTitle = $derived.by(() => {
    const path = $page.url.pathname;
    if (path === '/') return TITLES['/'];
    const hit = Object.keys(TITLES).find((p) => p !== '/' && path.startsWith(p));
    return hit ? TITLES[hit] : PRODUCT_NAME;
  });
</script>

<svelte:head>
  <!-- Trusted, build-time plugin output (the manifest <link> tag). -->
  {@html webManifestLink}
</svelte:head>

{#if auth.loading}
  <div class="flex min-h-screen items-center justify-center bg-base">
    <div class="flex flex-col items-center gap-4">
      <div
        class="h-9 w-9 animate-spin rounded-full border-[3px] border-accent border-t-transparent"
      ></div>
      <p class="text-sm text-ink-3">Loading…</p>
    </div>
  </div>
{:else if auth.user}
  <div class="flex h-screen overflow-hidden bg-base">
    <div class="hidden lg:block">
      <Sidebar />
    </div>

    <div class="flex flex-1 flex-col overflow-hidden">
      <Header title={pageTitle} />
      <!-- pb clears the fixed mobile tab bar; reset on lg where it's hidden. -->
      <main
        class="flex-1 overflow-y-auto p-4 pb-[calc(5.5rem+env(safe-area-inset-bottom))] lg:p-6 lg:pb-6"
      >
        {@render children()}
      </main>
    </div>

    <BottomNav />
  </div>
{:else}
  <div class="flex min-h-screen items-center justify-center bg-base px-4">
    <div class="text-center">
      <h1 class="text-xl font-semibold text-ink">Not signed in</h1>
      <p class="mt-2 text-sm text-ink-3">
        This app is protected by single sign-on. Sign in through your identity provider to continue.
      </p>
    </div>
  </div>
{/if}
