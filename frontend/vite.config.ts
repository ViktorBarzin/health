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
    // SCOPE: shell precache only. Offline *data logging* (the IndexedDB write
    // queue) is a later slice (#6, ADR-0005) and will switch this to the
    // `injectManifest` strategy with a custom service worker. For now Workbox
    // generates a minimal SW that precaches the built client assets and serves
    // navigations network-first, with `/api/*` deliberately never cached.
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
        theme_color: '#10b981',
        background_color: '#020617',
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
