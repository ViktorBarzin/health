<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import type {
    ExperienceLevel,
    GenerateProgramRequest,
    QuizOptions,
    TrainingGoal,
  } from '$lib/types';

  // Guided quiz (#13, ADR-0004): four questions — goal, days/week, experience,
  // session length — fed to the deterministic generator, which derives every
  // training number from the Principles KB. Mobile-first single-column form;
  // option sets come from the API so nothing is hardcoded here.
  let options = $state<QuizOptions | null>(null);
  let loading = $state(true);
  let error = $state('');
  let submitting = $state(false);

  let goal = $state<TrainingGoal | null>(null);
  let experience = $state<ExperienceLevel | null>(null);
  let days = $state<number | null>(null);
  let minutes = $state<number | null>(null);

  $effect(() => {
    load();
  });

  async function load() {
    loading = true;
    error = '';
    try {
      options = await api.get<QuizOptions>('/api/programs/quiz-options');
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load the quiz';
    } finally {
      loading = false;
    }
  }

  let ready = $derived(
    goal !== null && experience !== null && days !== null && minutes !== null,
  );

  async function generate() {
    if (!ready || submitting) return;
    submitting = true;
    error = '';
    try {
      const body: GenerateProgramRequest = {
        goal: goal!,
        experience: experience!,
        days_per_week: days!,
        session_minutes: minutes!,
      };
      const created = await api.post<{ id: string }>('/api/programs/generate', body);
      await goto(`/programs/${created.id}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to generate program';
      submitting = false;
    }
  }

  const expBlurb: Record<string, string> = {
    beginner: 'New to lifting (< 1 year)',
    intermediate: '1–3 years of training',
    advanced: '3+ years of training',
  };
</script>

<div class="space-y-6 pb-28">
  <div class="flex items-center gap-3">
    <a
      href="/programs"
      class="shrink-0 p-2 -ml-2 rounded-lg text-surface-400 hover:text-surface-200 hover:bg-surface-800 transition-colors"
      aria-label="Back to Programs"
    >
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
      </svg>
    </a>
    <div>
      <h1 class="text-2xl font-semibold text-surface-100">Build my program</h1>
      <p class="text-xs text-surface-500">Every number comes from peer-reviewed studies.</p>
    </div>
  </div>

  {#if error}
    <div class="p-4 rounded-xl bg-red-500/10 border border-red-500/30">
      <p class="text-sm text-red-400">{error}</p>
      <button onclick={load} class="mt-2 text-xs font-medium text-red-300 underline underline-offset-2">
        Try again
      </button>
    </div>
  {/if}

  {#if loading}
    <div class="space-y-4">
      {#each Array(4) as _}
        <div class="h-24 bg-surface-800 rounded-xl border border-surface-700 animate-pulse"></div>
      {/each}
    </div>
  {:else if options}
    <!-- Goal -->
    <fieldset class="space-y-2">
      <legend class="text-sm font-semibold text-surface-200 mb-2">What's your goal?</legend>
      <div class="grid grid-cols-2 gap-2">
        {#each options.goals as g (g.value)}
          <button
            type="button"
            onclick={() => (goal = g.value)}
            class="py-3 rounded-xl border text-sm font-medium transition-colors {goal === g.value
              ? 'bg-primary-500/20 border-primary-500 text-primary-200'
              : 'bg-surface-800 border-surface-700 text-surface-300 hover:border-surface-600'}"
          >
            {g.label}
          </button>
        {/each}
      </div>
    </fieldset>

    <!-- Days per week -->
    <fieldset class="space-y-2">
      <legend class="text-sm font-semibold text-surface-200 mb-2">How many days a week?</legend>
      <div class="flex flex-wrap gap-2">
        {#each options.days_per_week as d (d)}
          <button
            type="button"
            onclick={() => (days = d)}
            class="w-12 h-12 rounded-xl border text-sm font-semibold tabular-nums transition-colors {days === d
              ? 'bg-primary-500/20 border-primary-500 text-primary-200'
              : 'bg-surface-800 border-surface-700 text-surface-300 hover:border-surface-600'}"
          >
            {d}
          </button>
        {/each}
      </div>
    </fieldset>

    <!-- Experience -->
    <fieldset class="space-y-2">
      <legend class="text-sm font-semibold text-surface-200 mb-2">Your experience?</legend>
      <div class="space-y-2">
        {#each options.experience_levels as e (e.value)}
          <button
            type="button"
            onclick={() => (experience = e.value)}
            class="w-full flex items-center justify-between px-4 py-3 rounded-xl border text-left transition-colors {experience === e.value
              ? 'bg-primary-500/20 border-primary-500'
              : 'bg-surface-800 border-surface-700 hover:border-surface-600'}"
          >
            <span class="text-sm font-medium {experience === e.value ? 'text-primary-200' : 'text-surface-200'}">{e.label}</span>
            <span class="text-xs text-surface-500">{expBlurb[e.value] ?? ''}</span>
          </button>
        {/each}
      </div>
    </fieldset>

    <!-- Session length -->
    <fieldset class="space-y-2">
      <legend class="text-sm font-semibold text-surface-200 mb-2">How long per session?</legend>
      <div class="flex flex-wrap gap-2">
        {#each options.session_minutes as m (m)}
          <button
            type="button"
            onclick={() => (minutes = m)}
            class="px-4 h-12 rounded-xl border text-sm font-semibold tabular-nums transition-colors {minutes === m
              ? 'bg-primary-500/20 border-primary-500 text-primary-200'
              : 'bg-surface-800 border-surface-700 text-surface-300 hover:border-surface-600'}"
          >
            {m} min
          </button>
        {/each}
      </div>
    </fieldset>
  {/if}
</div>

<!-- Sticky generate bar -->
{#if !loading && options}
  <div class="fixed inset-x-0 bottom-16 sm:bottom-0 px-4 pb-3 pt-2 bg-gradient-to-t from-surface-900 via-surface-900/95 to-transparent">
    <div class="max-w-2xl mx-auto">
      <button
        onclick={generate}
        disabled={!ready || submitting}
        class="w-full flex items-center justify-center gap-2 py-3.5 rounded-2xl bg-primary-500 hover:bg-primary-600 text-white font-semibold text-base transition-colors disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-primary-500/20"
      >
        {#if submitting}
          <div class="w-5 h-5 border-2 border-white/50 border-t-transparent rounded-full animate-spin"></div>
          Generating…
        {:else}
          Generate my program
        {/if}
      </button>
    </div>
  </div>
{/if}
