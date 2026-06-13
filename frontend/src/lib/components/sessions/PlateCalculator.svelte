<script lang="ts">
  import { platesPerSide, type GymEquipment } from '$lib/plates';
  import { warmupRamp } from '$lib/warmup';
  import { formatWeight } from '$lib/utils/format';

  // A mobile bottom-sheet the user taps at the rack to see (a) the per-side plate
  // breakdown for a working weight and (b) a warm-up ramp up to it — both from
  // their Gym Profile's bar + plates, computed PURELY client-side (lib/plates.ts,
  // lib/warmup.ts). Opened from a set row; the target seeds from that set's weight
  // and can be nudged here without touching the logged set.
  let {
    open = false,
    weightKg = 0,
    reps = 8,
    equipment,
    onclose,
  }: {
    open?: boolean;
    weightKg?: number;
    reps?: number;
    equipment: GymEquipment | null;
    onclose: () => void;
  } = $props();

  // Local, editable target seeded from the set's weight each time the sheet
  // OPENS (a once-per-open seed, so the user can nudge `target` while it's open
  // without it snapping back). `seeded` resets on close so reopening the same
  // set — even at an unchanged weight — re-seeds from the set again.
  let target = $state(0);
  let seeded = $state(false);
  $effect(() => {
    if (open && !seeded) {
      seeded = true;
      target = weightKg;
    } else if (!open && seeded) {
      seeded = false;
    }
  });

  let result = $derived(
    equipment && equipment.bar > 0
      ? platesPerSide(target, equipment)
      : null,
  );
  let ramp = $derived(
    equipment && equipment.bar > 0
      ? warmupRamp(target, { equipment, workingReps: reps })
      : [],
  );

  function nudge(delta: number) {
    target = Math.max(0, Math.round((target + delta) * 100) / 100);
  }
</script>

{#if open}
  <button class="fixed inset-0 bg-black/60 z-40" onclick={onclose} aria-label="Close plate calculator"></button>
  <div
    class="fixed bottom-0 inset-x-0 z-50 bg-surface-900 border-t border-surface-700
           rounded-t-2xl pb-[env(safe-area-inset-bottom)] shadow-2xl flex flex-col"
    style="max-height: 85vh;"
    role="dialog"
    aria-label="Plate calculator"
  >
    <div class="mx-auto my-2 h-1 w-10 rounded-full bg-surface-600 shrink-0"></div>

    <div class="px-4 pb-3 shrink-0 flex items-center justify-between">
      <h2 class="text-base font-semibold text-surface-100">Plate calculator</h2>
      <button onclick={onclose} class="text-surface-400 hover:text-surface-200 p-1" aria-label="Close">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
      </button>
    </div>

    <div class="flex-1 overflow-y-auto px-4 pb-6 space-y-5">
      {#if !equipment || equipment.bar === 0}
        <div class="text-center py-8">
          <p class="text-sm text-surface-400">Set up your bar and plates in your Gym Profile to use the calculator.</p>
          <a href="/settings" class="inline-block mt-3 px-4 py-2 rounded-lg bg-primary-500/20 text-primary-300 text-sm font-medium">Open Gym Profile</a>
        </div>
      {:else}
        <!-- Target stepper -->
        <div class="flex items-center justify-center gap-2">
          <button onclick={() => nudge(-2.5)} class="w-10 h-10 rounded-lg bg-surface-800 border border-surface-700 text-surface-200 text-xl font-medium hover:bg-surface-700" aria-label="Decrease target">−</button>
          <div class="relative">
            <input type="number" inputmode="decimal" step="2.5" bind:value={target} class="w-28 text-center py-2 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 text-xl font-bold focus:outline-none focus:border-primary-500" aria-label="Target weight in kg" />
            <span class="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-surface-500 pointer-events-none">kg</span>
          </div>
          <button onclick={() => nudge(2.5)} class="w-10 h-10 rounded-lg bg-surface-800 border border-surface-700 text-surface-200 text-xl font-medium hover:bg-surface-700" aria-label="Increase target">+</button>
        </div>

        <!-- Plate breakdown -->
        {#if result}
          <div class="rounded-xl bg-surface-800 border border-surface-700 p-4">
            <p class="text-[0.65rem] uppercase tracking-wide text-surface-500 font-semibold mb-2">Per side</p>
            {#if result.perSide.length > 0}
              <div class="flex flex-wrap items-center gap-1.5">
                {#each result.perSide as p, i (i)}
                  <span class="px-2.5 py-1 rounded-md bg-primary-500/15 text-primary-200 text-sm font-semibold">{formatWeight(p)}</span>
                {/each}
              </div>
            {:else}
              <p class="text-sm text-surface-300">Bare bar — no plates.</p>
            {/if}
            <p class="mt-3 text-sm text-surface-400">
              Loads <span class="text-surface-100 font-semibold">{formatWeight(result.total)} kg</span>
              <span class="text-surface-600">({formatWeight(equipment.bar)} kg bar)</span>
              {#if !result.exact}
                <span class="block mt-1 text-amber-400 text-xs">⚠ {formatWeight(target)} kg isn't loadable — this is the closest.</span>
              {/if}
            </p>
          </div>
        {/if}

        <!-- Warm-up ramp -->
        {#if ramp.length > 1}
          <div>
            <p class="text-[0.65rem] uppercase tracking-wide text-surface-500 font-semibold mb-2">Warm-up ramp</p>
            <ul class="space-y-1.5">
              {#each ramp as w, i (i)}
                <li class="flex items-center justify-between px-3 py-2 rounded-lg bg-surface-800 border border-surface-700">
                  <span class="text-xs text-surface-500 w-12">Set {i + 1}</span>
                  <span class="text-sm font-semibold text-surface-100">{formatWeight(w.weight)} kg</span>
                  <span class="text-sm text-surface-400">× {w.reps}</span>
                </li>
              {/each}
            </ul>
          </div>
        {/if}
      {/if}
    </div>
  </div>
{/if}
