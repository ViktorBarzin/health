<script lang="ts">
  import { api } from '$lib/api';
  import type { ExerciseSummary, MuscleOption } from '$lib/types';

  // The shared Exercise library: global (seeded) Exercises plus the user's own
  // custom ones. Mobile-first browse — search by name, filter by muscle and/or
  // equipment. Server-side filtering keeps the ~870-row catalog responsive.
  let exercises = $state<ExerciseSummary[]>([]);
  let muscles = $state<MuscleOption[]>([]);
  let equipment = $state<string[]>([]);
  let loading = $state(true);
  let error = $state('');

  let search = $state('');
  let muscle = $state('');
  let equip = $state('');

  // Load filter options once; they don't change as the user types.
  $effect(() => {
    loadFilterOptions();
  });

  // Re-query whenever a filter changes, debounced so each keystroke doesn't fire
  // a request.
  let debounce: ReturnType<typeof setTimeout>;
  $effect(() => {
    const _s = search;
    const _m = muscle;
    const _e = equip;
    clearTimeout(debounce);
    debounce = setTimeout(() => loadExercises(), 200);
    return () => clearTimeout(debounce);
  });

  async function loadFilterOptions() {
    try {
      [muscles, equipment] = await Promise.all([
        api.get<MuscleOption[]>('/api/exercises/muscles'),
        api.get<string[]>('/api/exercises/equipment'),
      ]);
    } catch {
      // Non-fatal: the list still works without filter dropdowns populated.
    }
  }

  async function loadExercises() {
    loading = true;
    error = '';
    try {
      // The whole catalog (~870 global + the user's custom) fits one page; the
      // API caps limit at 1000. Client-side this stays snappy and lets search/
      // filter feel instant once loaded.
      const params = new URLSearchParams({ limit: '1000' });
      if (search.trim()) params.set('search', search.trim());
      if (muscle) params.set('muscle', muscle);
      if (equip) params.set('equipment', equip);
      exercises = await api.get<ExerciseSummary[]>(`/api/exercises/?${params}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load exercises';
    } finally {
      loading = false;
    }
  }

  function clearFilters() {
    search = '';
    muscle = '';
    equip = '';
  }

  function titleCase(s: string): string {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  let hasFilters = $derived(!!(search.trim() || muscle || equip));
</script>

<div class="space-y-4">
  <!-- Search -->
  <div class="relative">
    <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-surface-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
    </svg>
    <input
      type="text"
      bind:value={search}
      placeholder="Search exercises..."
      class="w-full pl-10 pr-4 py-2.5 bg-surface-800 border border-surface-700 rounded-lg
             text-surface-100 placeholder-surface-500 text-sm
             focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500
             transition-colors"
    />
  </div>

  <!-- Filters + New -->
  <div class="flex flex-wrap items-center gap-2">
    <div class="relative">
      <select
        bind:value={muscle}
        class="appearance-none bg-surface-800 border border-surface-700 rounded-lg pl-3 pr-8 py-2
               text-sm text-surface-200 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500
               transition-colors cursor-pointer"
      >
        <option value="">All muscles</option>
        {#each muscles as m}
          <option value={m.value}>{m.label}</option>
        {/each}
      </select>
      <svg class="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
      </svg>
    </div>

    <div class="relative">
      <select
        bind:value={equip}
        class="appearance-none bg-surface-800 border border-surface-700 rounded-lg pl-3 pr-8 py-2
               text-sm text-surface-200 focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500
               transition-colors cursor-pointer"
      >
        <option value="">All equipment</option>
        {#each equipment as e}
          <option value={e}>{titleCase(e)}</option>
        {/each}
      </select>
      <svg class="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
      </svg>
    </div>

    {#if hasFilters}
      <button
        onclick={clearFilters}
        class="px-3 py-2 text-sm text-surface-400 hover:text-surface-200 transition-colors"
      >
        Clear
      </button>
    {/if}

    <a
      href="/exercises/new"
      class="ml-auto inline-flex items-center gap-1.5 px-3 py-2 bg-primary-500/15 hover:bg-primary-500/25
             text-primary-300 text-sm font-medium rounded-lg transition-colors"
    >
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
      </svg>
      New
    </a>
  </div>

  {#if loading}
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {#each Array(9) as _}
        <div class="bg-surface-800 rounded-xl border border-surface-700 p-4 animate-pulse">
          <div class="flex gap-3">
            <div class="w-14 h-14 bg-surface-700 rounded-lg shrink-0"></div>
            <div class="flex-1 space-y-2 pt-1">
              <div class="w-3/4 h-4 bg-surface-700 rounded"></div>
              <div class="w-1/2 h-3 bg-surface-700 rounded"></div>
            </div>
          </div>
        </div>
      {/each}
    </div>
  {:else if error}
    <div class="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400">{error}</p>
      <button
        class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm transition-colors"
        onclick={loadExercises}
      >
        Retry
      </button>
    </div>
  {:else if exercises.length === 0}
    <div class="p-12 text-center bg-surface-800 rounded-xl border border-surface-700">
      <svg class="w-12 h-12 text-surface-600 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
      </svg>
      <p class="text-surface-400 text-sm">No exercises found.</p>
    </div>
  {:else}
    <p class="text-xs text-surface-500">{exercises.length} exercise{exercises.length !== 1 ? 's' : ''}</p>
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
      {#each exercises as ex (ex.id)}
        <a
          href="/exercises/{ex.id}"
          class="group flex gap-3 bg-surface-800 rounded-xl border border-surface-700 p-4
                 hover:border-surface-600 hover:bg-surface-800/80 transition-all"
        >
          <div class="w-14 h-14 rounded-lg bg-surface-700 overflow-hidden shrink-0 flex items-center justify-center">
            {#if ex.images.length > 0}
              <img src={ex.images[0]} alt={ex.name} loading="lazy" class="w-full h-full object-cover" />
            {:else}
              <svg class="w-6 h-6 text-surface-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6.75 6.75v10.5m10.5-10.5v10.5M4.5 9.75h2.25m10.5 0H19.5M4.5 14.25h2.25m10.5 0H19.5M6.75 12h10.5" />
              </svg>
            {/if}
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-start gap-2">
              <h3 class="text-sm font-medium text-surface-200 group-hover:text-surface-100 transition-colors leading-snug">
                {ex.name}
              </h3>
              {#if ex.is_custom}
                <span class="shrink-0 text-[0.6rem] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded
                             bg-primary-500/15 text-primary-300">Custom</span>
              {/if}
            </div>
            <div class="mt-1.5 flex flex-wrap gap-1">
              {#each ex.primary_muscles as m}
                <span class="text-[0.65rem] px-1.5 py-0.5 rounded bg-surface-700 text-surface-300">{m}</span>
              {/each}
              {#if ex.equipment}
                <span class="text-[0.65rem] px-1.5 py-0.5 rounded bg-surface-700/50 text-surface-400">{ex.equipment}</span>
              {/if}
            </div>
          </div>
        </a>
      {/each}
    </div>
  {/if}
</div>
