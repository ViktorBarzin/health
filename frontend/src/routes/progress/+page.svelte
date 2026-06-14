<script lang="ts">
  // Progress review hub (ADR-0008): the landing for everything you *review*
  // rather than *do*. Slice 1 ships the hub + links; slice 7 enriches each
  // screen and mounts the date-range control here.
  import { MORE_GROUPS } from '$lib/nav';

  const reviewItems = MORE_GROUPS.find((g) => g.title === 'Progress')?.items ?? [];

  const blurb: Record<string, string> = {
    '/metrics': 'Heart rate, HRV, SpO₂ and every health time-series.',
    '/trends': 'Long-range trends across your metrics.',
    '/body': 'Body mass and composition over time.',
    '/sleep': 'Sleep stages, duration and consistency.',
    '/analytics': 'Per-muscle recovery, volume and strength trends.',
  };
</script>

<div class="mx-auto max-w-2xl">
  <header class="mb-5">
    <h1 class="text-2xl font-semibold tracking-tight text-ink">Progress</h1>
    <p class="mt-1 text-sm text-ink-2">Review your training and health history.</p>
  </header>

  <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
    {#each reviewItems as item (item.href)}
      <a
        href={item.href}
        class="group flex items-start gap-3 rounded-2xl border border-edge bg-panel p-4 transition-colors hover:border-edge-strong"
      >
        <span
          class="grid h-10 w-10 flex-shrink-0 place-items-center rounded-xl bg-accent-soft text-accent-ink"
        >
          <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.7">
            <path stroke-linecap="round" stroke-linejoin="round" d={item.icon} />
          </svg>
        </span>
        <span class="min-w-0">
          <span class="block font-semibold text-ink">{item.label}</span>
          <span class="mt-0.5 block text-xs leading-relaxed text-ink-3">{blurb[item.href] ?? ''}</span>
        </span>
      </a>
    {/each}
  </div>
</div>
