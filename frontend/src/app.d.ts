// Ambient types for the vite-plugin-pwa virtual modules used by the PWA shell
// (ADR-0007). `virtual:pwa-info` exposes the generated web-manifest link tag so
// the layout can inject it into <svelte:head>; `virtual:pwa-register/svelte`
// is available for a future update-prompt UI.
import 'vite-plugin-pwa/svelte';
import 'vite-plugin-pwa/info';

declare global {
  // See https://svelte.dev/docs/kit/types#app
  namespace App {
    // interface Error {}
    // interface Locals {}
    // interface PageData {}
    // interface PageState {}
    // interface Platform {}
  }
}

export {};
