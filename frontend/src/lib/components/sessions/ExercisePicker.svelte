<script lang="ts">
  import { api } from '$lib/api';
  import type { ExerciseSummary } from '$lib/types';

  // A mobile bottom-sheet for picking an Exercise from the shared library
  // (global ∪ the user's custom). Used when adding Sets to a Session. Searches
  // server-side, debounced, so the ~870-row catalog stays responsive.
  let {
    open = false,
    onpick,
    onclose,
  }: {
    open?: boolean;
    onpick: (exercise: ExerciseSummary) => void;
    onclose: () => void;
  } = $props();

  let exercises = $state<ExerciseSummary[]>([]);
  let search = $state('');
  let loading = $state(false);
  let error = $state('');

  // Reload when the sheet opens or the query changes (debounced).
  let debounce: ReturnType<typeof setTimeout>;
  $effect(() => {
    if (!open) return;
    const _s = search;
    clearTimeout(debounce);
    debounce = setTimeout(() => load(), 200);
    return () => clearTimeout(debounce);
  });

  async function load() {
    loading = true;
    error = '';
    try {
      const params = new URLSearchParams({ limit: '50' });
      if (search.trim()) params.set('search', search.trim());
      exercises = await api.get<ExerciseSummary[]>(`/api/exercises/?${params}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load exercises';
    } finally {
      loading = false;
    }
  }

  function pick(ex: ExerciseSummary) {
    search = '';
    onpick(ex);
  }
</script>

{#if open}
  <button
    class="fixed inset-0 bg-black/60 z-40"
    onclick={onclose}
    aria-label="Close exercise picker"
  ></button>
  <div
    class="fixed bottom-0 inset-x-0 z-50 bg-surface-900 border-t border-surface-700
           rounded-t-2xl pb-[env(safe-area-inset-bottom)] shadow-2xl flex flex-col"
    style="max-height: 85vh;"
    role="dialog"
    aria-label="Pick an exercise"
  >
    <div class="mx-auto my-2 h-1 w-10 rounded-full bg-surface-600 shrink-0"></div>

    <div class="px-4 pb-3 shrink-0">
      <div class="flex items-center justify-between mb-3">
        <h2 class="text-base font-semibold text-surface-100">Add exercise</h2>
        <button onclick={onclose} class="text-surface-400 hover:text-surface-200 p-1" aria-label="Close">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div class="relative">
        <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-surface-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
        </svg>
        <!-- svelte-ignore a11y_autofocus -->
        <input
          type="text"
          bind:value={search}
          autofocus
          placeholder="Search exercises…"
          class="w-full pl-10 pr-4 py-2.5 bg-surface-800 border border-surface-700 rounded-lg
                 text-surface-100 placeholder-surface-500 text-base
                 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 transition-colors"
        />
      </div>
    </div>

    <div class="flex-1 overflow-y-auto px-4 pb-4">
      {#if loading && exercises.length === 0}
        <div class="space-y-2">
          {#each Array(6) as _}
            <div class="h-14 bg-surface-800 rounded-lg animate-pulse"></div>
          {/each}
        </div>
      {:else if error}
        <p class="text-sm text-red-400 py-4">{error}</p>
      {:else if exercises.length === 0}
        <p class="text-sm text-surface-500 py-8 text-center">No exercises found.</p>
      {:else}
        <ul class="space-y-1.5">
          {#each exercises as ex (ex.id)}
            <li>
              <button
                onclick={() => pick(ex)}
                class="w-full flex items-center gap-3 p-2.5 rounded-lg text-left
                       bg-surface-800 border border-surface-700 hover:border-primary-500/50 hover:bg-surface-800/80 transition-all"
              >
                <div class="w-10 h-10 rounded-md bg-surface-700 overflow-hidden shrink-0 flex items-center justify-center">
                  {#if ex.images.length > 0}
                    <img src={ex.images[0]} alt={ex.name} loading="lazy" class="w-full h-full object-cover" />
                  {:else}
                    <svg class="w-5 h-5 text-surface-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 6.75v10.5m10.5-10.5v10.5M4.5 9.75h2.25m10.5 0H19.5M4.5 14.25h2.25m10.5 0H19.5M6.75 12h10.5" />
                    </svg>
                  {/if}
                </div>
                <div class="min-w-0 flex-1">
                  <p class="text-sm font-medium text-surface-200 truncate">{ex.name}</p>
                  {#if ex.primary_muscles.length > 0 || ex.equipment}
                    <p class="text-xs text-surface-500 truncate">
                      {[...ex.primary_muscles, ex.equipment].filter(Boolean).join(' · ')}
                    </p>
                  {/if}
                </div>
                {#if ex.is_custom}
                  <span class="shrink-0 text-[0.55rem] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-primary-500/15 text-primary-300">Custom</span>
                {/if}
              </button>
            </li>
          {/each}
        </ul>
      {/if}
    </div>
  </div>
{/if}
