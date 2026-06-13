<script lang="ts">
  import { prLabel, type PRResult } from '$lib/pr';

  // The live PR celebration (CONTEXT.md "PR": detected live as a Set is logged —
  // offline included — and celebrated in the UI). Mobile-first and NON-BLOCKING:
  // a toast banner pinned above the finish bar that auto-dismisses; it never
  // interrupts logging. Driven by the client-side detector (lib/pr.ts) so it
  // fires instantly with no server round-trip; the server reconciles on sync.
  let {
    prs = [],
    onclose,
  }: {
    /** The PRs to celebrate. Empty = nothing shown. */
    prs?: PRResult[];
    onclose: () => void;
  } = $props();

  // Auto-dismiss after a few seconds; reset the timer whenever a new batch lands.
  let timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    if (prs.length === 0) return;
    if (timer) clearTimeout(timer);
    timer = setTimeout(onclose, 4000);
    return () => {
      if (timer) clearTimeout(timer);
    };
  });

  // Order the dimensions consistently when several fire at once: the most
  // headline-worthy first (weight, then 1RM, then reps@weight, then volume).
  const ORDER = ['weight', 'e1rm', 'reps_at_weight', 'volume'] as const;
  let ordered = $derived(
    [...prs].sort((a, b) => ORDER.indexOf(a.kind) - ORDER.indexOf(b.kind)),
  );
</script>

{#if prs.length > 0}
  <!-- Pinned above the bottom nav + finish bar; pointer-events only on the card
       so taps elsewhere keep logging (non-blocking). -->
  <div
    class="fixed bottom-[calc(7rem+env(safe-area-inset-bottom))] lg:bottom-20 inset-x-0 z-30 px-3 pointer-events-none"
    role="status"
    aria-live="polite"
  >
    <div class="max-w-3xl mx-auto lg:pl-64">
      <div
        class="pointer-events-auto flex items-start gap-3 rounded-2xl border border-amber-400/40
               bg-gradient-to-br from-amber-500/95 to-orange-600/95 text-white shadow-2xl
               px-4 py-3 animate-[pr-pop_0.28s_ease-out]"
      >
        <div class="text-2xl leading-none mt-0.5" aria-hidden="true">🏆</div>
        <div class="flex-1 min-w-0">
          <p class="text-sm font-bold tracking-tight">
            {ordered.length === 1 ? 'Personal record!' : `${ordered.length} new PRs!`}
          </p>
          <ul class="mt-0.5 space-y-0.5">
            {#each ordered as pr (pr.kind + '-' + (pr.atWeightKg ?? ''))}
              <li class="text-xs font-medium text-amber-50/95 truncate">{prLabel(pr)}</li>
            {/each}
          </ul>
        </div>
        <button
          onclick={onclose}
          class="shrink-0 -mr-1 -mt-0.5 p-1 text-amber-50/80 hover:text-white transition-colors"
          aria-label="Dismiss"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  @keyframes pr-pop {
    0% {
      opacity: 0;
      transform: translateY(0.5rem) scale(0.97);
    }
    100% {
      opacity: 1;
      transform: translateY(0) scale(1);
    }
  }
</style>
