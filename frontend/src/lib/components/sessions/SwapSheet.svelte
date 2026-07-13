<script lang="ts">
  import type { SwapAlternative } from '$lib/swap';
  import { muscleLabel } from '$lib/muscle-heat';
  import { formatWeight } from '$lib/utils/format';

  // The Swap bottom-sheet (CONTEXT.md "Swap"): "this station is taken — give me
  // an equivalent". Lists the ranked alternatives prefetched for the outgoing
  // Exercise (same primary muscles, your equipment, Recovery-aware, trained
  // movements first), each prescribed off its OWN history. Also carries the
  // explicit Exclusion action ("don't suggest this again") — two-tap to confirm,
  // reversible in Settings.
  let {
    open = false,
    exerciseName,
    alternatives,
    offline = false,
    onpick,
    onexclude,
    onclose,
  }: {
    open?: boolean;
    /** The outgoing Exercise's display name. */
    exerciseName: string;
    /** Ranked equivalents; null = still loading / unavailable. */
    alternatives: SwapAlternative[] | null;
    /** True when the list came from (or failed against) a dead connection. */
    offline?: boolean;
    onpick: (alt: SwapAlternative) => void;
    /** Present = show the "don't suggest again" action. */
    onexclude?: () => void;
    onclose: () => void;
  } = $props();

  // Exclusion is deliberately two-tap: it's a standing engine constraint, not a
  // one-day tweak, so an accidental brush shouldn't set it.
  let confirmingExclude = $state(false);
  $effect(() => {
    if (!open) confirmingExclude = false;
  });

  function tapExclude() {
    if (!confirmingExclude) {
      confirmingExclude = true;
      return;
    }
    confirmingExclude = false;
    onexclude?.();
  }
</script>

{#if open}
  <button class="fixed inset-0 bg-black/60 z-40" onclick={onclose} aria-label="Close swap sheet"></button>
  <div
    class="fixed bottom-0 inset-x-0 z-50 bg-surface-900 border-t border-surface-700
           rounded-t-2xl pb-[env(safe-area-inset-bottom)] shadow-2xl flex flex-col"
    style="max-height: 80vh;"
    role="dialog"
    aria-label="Swap exercise"
  >
    <div class="mx-auto my-2 h-1 w-10 rounded-full bg-surface-600 shrink-0"></div>

    <div class="px-4 pb-3 shrink-0 flex items-center justify-between">
      <div class="min-w-0">
        <h2 class="text-base font-semibold text-surface-100">Swap exercise</h2>
        <p class="text-xs text-surface-500 truncate">Replaces {exerciseName} for today</p>
      </div>
      <button onclick={onclose} class="text-surface-400 hover:text-surface-200 p-1" aria-label="Close">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>

    <div class="flex-1 overflow-y-auto px-4 pb-4">
      {#if alternatives === null}
        <div class="space-y-2">
          {#each Array(4) as _}
            <div class="h-16 bg-surface-800 rounded-lg animate-pulse"></div>
          {/each}
        </div>
      {:else if alternatives.length === 0}
        <div class="py-8 text-center">
          <p class="text-sm text-surface-400">
            {#if offline}
              No equivalents cached for offline use.
            {:else}
              No equivalents match your equipment.
            {/if}
          </p>
          <p class="mt-1 text-xs text-surface-600">
            You can still add any movement via “Add exercise”.
          </p>
        </div>
      {:else}
        <ul class="space-y-1.5">
          {#each alternatives as alt (alt.exercise_id)}
            <li>
              <button
                onclick={() => onpick(alt)}
                class="w-full flex items-center gap-3 p-3 rounded-lg text-left
                       bg-surface-800 border border-surface-700 hover:border-primary-500/50 transition-all"
              >
                <div class="min-w-0 flex-1">
                  <p class="text-sm font-medium text-surface-200 truncate">{alt.name}</p>
                  <p class="text-xs text-surface-500 truncate">
                    {[
                      alt.shared_muscles.map(muscleLabel).join(', '),
                      alt.equipment ?? 'no equipment',
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  </p>
                </div>
                <div class="shrink-0 text-right">
                  {#if alt.is_starting_point}
                    <p class="text-xs font-medium text-surface-400">pick a weight</p>
                  {:else}
                    <p class="text-sm font-semibold text-primary-300 tabular-nums">
                      {formatWeight(alt.target_weight_kg)} kg × {alt.target_reps}
                    </p>
                  {/if}
                  {#if alt.has_history}
                    <p class="text-[0.6rem] font-semibold uppercase tracking-wide text-emerald-400/90">Trained</p>
                  {:else}
                    <p class="text-[0.6rem] font-semibold uppercase tracking-wide text-surface-500">New to you</p>
                  {/if}
                </div>
              </button>
            </li>
          {/each}
        </ul>
      {/if}

      {#if onexclude}
        <div class="mt-4 pt-3 border-t border-surface-700/60">
          <button
            onclick={tapExclude}
            class="w-full py-2.5 rounded-lg text-xs font-medium transition-colors
                   {confirmingExclude
              ? 'bg-red-500/15 text-red-300 border border-red-500/40'
              : 'text-surface-500 hover:text-surface-300'}"
          >
            {#if confirmingExclude}
              Tap again — never recommend {exerciseName} (undo in Settings)
            {:else}
              Don't suggest {exerciseName} again
            {/if}
          </button>
        </div>
      {/if}
    </div>
  </div>
{/if}
