import { defineConfig } from 'vitest/config';

// Unit tests for pure logic (e.g. src/lib/nav.ts). Deliberately does NOT load
// the SvelteKit or PWA plugins from vite.config.ts — those pull in virtual
// modules (virtual:pwa-info, $app/*) that unit-tested pure modules don't need.
export default defineConfig({
  test: {
    include: ['src/**/*.{test,spec}.{js,ts}'],
    environment: 'node'
  }
});
