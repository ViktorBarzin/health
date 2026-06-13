<script lang="ts">
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import { ApiError } from '$lib/api';
  import type { ExerciseDetail } from '$lib/types';

  let exerciseId = $derived($page.params.id);
  let exercise = $state<ExerciseDetail | null>(null);
  let loading = $state(true);
  let error = $state('');
  let notFound = $state(false);
  // Which image is shown (the dataset gives a start + end position per movement).
  let activeImage = $state(0);

  $effect(() => {
    const _id = exerciseId;
    activeImage = 0;
    loadExercise();
  });

  async function loadExercise() {
    loading = true;
    error = '';
    notFound = false;
    try {
      exercise = await api.get<ExerciseDetail>(`/api/exercises/${exerciseId}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        notFound = true;
      } else {
        error = err instanceof Error ? err.message : 'Failed to load exercise';
      }
    } finally {
      loading = false;
    }
  }

  function titleCase(s: string): string {
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // The dataset's descriptive fields, shown as a compact attribute strip.
  let attributes = $derived(
    exercise
      ? [
          ['Equipment', exercise.equipment],
          ['Category', exercise.category],
          ['Mechanic', exercise.mechanic],
          ['Force', exercise.force],
          ['Level', exercise.level],
        ].filter(([, v]) => !!v) as [string, string][]
      : []
  );
</script>

<div class="space-y-6 max-w-2xl mx-auto">
  <a href="/exercises" class="inline-flex items-center gap-1.5 text-sm text-surface-400 hover:text-surface-200 transition-colors">
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
    </svg>
    Exercises
  </a>

  {#if loading}
    <div class="space-y-4 animate-pulse">
      <div class="w-2/3 h-7 bg-surface-700 rounded"></div>
      <div class="w-full aspect-video bg-surface-800 rounded-xl"></div>
      <div class="w-full h-24 bg-surface-800 rounded-xl"></div>
    </div>
  {:else if notFound}
    <div class="p-12 text-center bg-surface-800 rounded-xl border border-surface-700">
      <p class="text-surface-300 font-medium">Exercise not found</p>
      <p class="text-surface-500 text-sm mt-1">It may be private to another user or no longer exist.</p>
    </div>
  {:else if error}
    <div class="p-6 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400">{error}</p>
      <button
        class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm transition-colors"
        onclick={loadExercise}
      >
        Retry
      </button>
    </div>
  {:else if exercise}
    <!-- Title -->
    <div class="flex items-start gap-3">
      <h1 class="text-2xl font-semibold text-surface-100 leading-tight">{exercise.name}</h1>
      {#if exercise.is_custom}
        <span class="shrink-0 mt-1 text-[0.65rem] font-semibold uppercase tracking-wide px-2 py-0.5 rounded
                     bg-primary-500/15 text-primary-300">Custom</span>
      {/if}
    </div>

    <!-- Image -->
    {#if exercise.images.length > 0}
      <div class="space-y-2">
        <div class="w-full aspect-video bg-surface-800 rounded-xl overflow-hidden border border-surface-700">
          <img src={exercise.images[activeImage]} alt={exercise.name} class="w-full h-full object-contain" />
        </div>
        {#if exercise.images.length > 1}
          <div class="flex gap-2">
            {#each exercise.images as img, i}
              <button
                onclick={() => (activeImage = i)}
                class="w-16 h-16 rounded-lg overflow-hidden border-2 transition-colors
                       {activeImage === i ? 'border-primary-500' : 'border-surface-700 hover:border-surface-500'}"
                aria-label={`Position ${i + 1}`}
              >
                <img src={img} alt={`${exercise.name} position ${i + 1}`} class="w-full h-full object-cover" />
              </button>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    <!-- Demo video deep link -->
    <a
      href={exercise.demo_video_url}
      target="_blank"
      rel="noopener noreferrer"
      class="flex items-center justify-center gap-2 w-full py-3 rounded-xl
             bg-red-500/15 hover:bg-red-500/25 text-red-300 font-medium text-sm transition-colors"
    >
      <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
        <path d="M21.582 6.186a2.506 2.506 0 00-1.768-1.768C18.254 4 12 4 12 4s-6.254 0-7.814.418a2.506 2.506 0 00-1.768 1.768C2 7.746 2 12 2 12s0 4.254.418 5.814a2.506 2.506 0 001.768 1.768C5.746 20 12 20 12 20s6.254 0 7.814-.418a2.506 2.506 0 001.768-1.768C22 16.254 22 12 22 12s0-4.254-.418-5.814zM10 15.464V8.536L16 12l-6 3.464z" />
      </svg>
      Watch proper form on YouTube
    </a>

    <!-- Muscles -->
    <div class="grid grid-cols-2 gap-3">
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
        <h3 class="text-xs font-semibold text-surface-400 uppercase tracking-wider mb-2">Primary muscles</h3>
        {#if exercise.primary_muscles.length > 0}
          <div class="flex flex-wrap gap-1.5">
            {#each exercise.primary_muscles as m}
              <span class="text-xs px-2 py-1 rounded-md bg-primary-500/15 text-primary-300">{titleCase(m)}</span>
            {/each}
          </div>
        {:else}
          <p class="text-sm text-surface-500">—</p>
        {/if}
      </div>
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
        <h3 class="text-xs font-semibold text-surface-400 uppercase tracking-wider mb-2">Secondary muscles</h3>
        {#if exercise.secondary_muscles.length > 0}
          <div class="flex flex-wrap gap-1.5">
            {#each exercise.secondary_muscles as m}
              <span class="text-xs px-2 py-1 rounded-md bg-surface-700 text-surface-300">{titleCase(m)}</span>
            {/each}
          </div>
        {:else}
          <p class="text-sm text-surface-500">—</p>
        {/if}
      </div>
    </div>

    <!-- Attributes -->
    {#if attributes.length > 0}
      <div class="flex flex-wrap gap-2">
        {#each attributes as [label, value]}
          <span class="text-xs px-2.5 py-1 rounded-lg bg-surface-800 border border-surface-700 text-surface-300">
            <span class="text-surface-500">{label}:</span> {titleCase(value)}
          </span>
        {/each}
      </div>
    {/if}

    <!-- Instructions -->
    {#if exercise.instructions.length > 0}
      <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
        <h3 class="text-sm font-semibold text-surface-200 mb-3">Instructions</h3>
        <ol class="space-y-3">
          {#each exercise.instructions as step, i}
            <li class="flex gap-3 text-sm text-surface-300">
              <span class="shrink-0 w-6 h-6 rounded-full bg-surface-700 text-surface-400 text-xs flex items-center justify-center font-medium">
                {i + 1}
              </span>
              <span class="leading-relaxed pt-0.5">{step}</span>
            </li>
          {/each}
        </ol>
      </div>
    {/if}
  {/if}
</div>
