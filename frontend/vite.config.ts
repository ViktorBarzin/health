import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { SvelteKitPWA } from '@vite-pwa/sveltekit';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [
    tailwindcss(),
    sveltekit(),
    // Mobile-first PWA shell (ADR-0007). The phone is the primary surface, so the
    // app is installable to the home screen and the shell loads fast offline.
    //
    // SCOPE: shell precache + offline navigation fallback. Offline *data logging*
    // (ADR-0005, #6) is handled IN THE PAGE by an IndexedDB write-queue + sync
    // engine (`src/lib/sync/*`), NOT by the service worker — so we stay on
    // `generateSW` rather than `injectManifest`. The SW's only job for offline-
    // first is to serve the app shell when there's no signal; the queue (running
    // in the page once the shell loads) captures every Set write locally and
    // drains it to `/api/sessions...` on reconnect. Caching mutation responses
    // would be WRONG — `/api/*` is deliberately never cached, and the queue owns
    // offline writes — so no SW-level `/api/sessions` interception is added.
    // Background-sync (draining while the app is closed) is intentionally out of
    // scope (YAGNI): the ADR only requires sync on reconnect + on reload.
    SvelteKitPWA({
      strategies: 'generateSW',
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      scope: '/',
      base: '/',
      manifest: {
        name: 'Health — Fitness Platform',
        short_name: 'Health',
        description: 'Self-hosted fitness platform: log Sessions, track training, own your data.',
        // Athletic Instrument identity (ADR-0008): near-black base, matching the
        // dark scheme-aware <meta theme-color> in app.html. name/short_name
        // mirror the brand token (lib/brand.ts) — the single source if renamed.
        theme_color: '#0a0a0b',
        background_color: '#0a0a0b',
        display: 'standalone',
        orientation: 'portrait',
        scope: '/',
        start_url: '/',
        categories: ['health', 'fitness', 'lifestyle'],
        icons: [
          { src: '/pwa-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/pwa-maskable-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: '/pwa-maskable-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }
        ]
      },
      workbox: {
        // Precache the built shell + static assets (the JS/CSS chunks, icons).
        // Server bundles are excluded by default (globIgnores: server/**).
        globPatterns: ['client/**/*.{js,css,ico,png,svg,webp,woff,woff2}'],
        // Disable Workbox's precache-backed navigation fallback. @vite-pwa/sveltekit
        // would otherwise default navigateFallback to '/', emitting a
        // NavigationRoute(createHandlerBoundToURL('/')). But '/' is NOT precached
        // here (adapter-node SSRs it — there is no static shell HTML on disk), so
        // that route would mis-serve navigations. Setting it explicitly to null
        // (a present-but-falsy key) stops the plugin overriding it AND tells
        // Workbox to skip the route; the runtime route below handles navigations.
        navigateFallback: null,
        runtimeCaching: [
          {
            // SSR page navigations: network-first so content stays fresh, falling
            // back to the last-seen page when offline. /api/* is explicitly
            // excluded here and matches no other route, so it ALWAYS hits the
            // network — mutations are never cached or served stale.
            urlPattern: ({ request, url }) =>
              request.mode === 'navigate' && !url.pathname.startsWith('/api/'),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'app-shell',
              networkTimeoutSeconds: 3,
              expiration: { maxEntries: 32, maxAgeSeconds: 60 * 60 * 24 * 7 },
              cacheableResponse: { statuses: [200] }
            }
          }
        ],
        // Web Push handlers (ADR-0010) ride into the generated worker without
        // an injectManifest migration: push-sw.js (static/) adds the push +
        // notificationclick listeners for the rest-timer notifications.
        importScripts: ['push-sw.js'],
        // A new SW takes over immediately so an install/update is never stuck
        // behind an old shell. Safe for shell-only caching (no data in flight).
        skipWaiting: true,
        clientsClaim: true,
        cleanupOutdatedCaches: true
      },
      devOptions: {
        // The SW is only meaningful for the built shell; leave it off in dev so
        // it never caches HMR assets. Verify via `vite build && vite preview`.
        enabled: false,
        type: 'module'
      }
    })
  ]
});
