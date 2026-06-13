<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import type { ProgramPreset, ProgramSummary } from '$lib/types';

  // Programs hub (#13, ADR-0004): browse the named-preset catalog and your own
  // generated Programs, or start the guided quiz. A preset is a pinned set of
  // quiz answers fed through the same deterministic generator — selecting one
  // generates a Program (numbers derived from the Principles KB). Mobile-first.
  let presets = $state<ProgramPreset[]>([]);
  let programs = $state<ProgramSummary[]>([]);
  let loading = $state(true);
  let error = $state('');
  let generatingKey = $state<string | null>(null);

  $effect(() => {
    load();
  });

  async function load() {
    loading = true;
    error = '';
    try {
      const [p, mine] = await Promise.all([
        api.get<ProgramPreset[]>('/api/programs/presets'),
        api.get<ProgramSummary[]>('/api/programs'),
      ]);
      presets = p;
      programs = mine;
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load programs';
    } finally {
      loading = false;
    }
  }

  async function startPreset(key: string) {
    if (generatingKey) return;
    generatingKey = key;
    error = '';
    try {
      const created = await api.post<{ id: string }>('/api/programs/generate', {
        preset_key: key,
      });
      await goto(`/programs/${created.id}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to start program';
      generatingKey = null;
    }
  }

  const goalLabel: Record<string, string> = {
    bulk: 'Build muscle',
    cut: 'Lose fat',
    maintain: 'Maintain',
    strength: 'Get stronger',
  };

  let activeProgram = $derived(programs.find((p) => p.status === 'active') ?? null);
  let archived = $derived(programs.filter((p) => p.status === 'archived'));
</script>

<div class="space-y-6 pb-24">
  <div>
    <h1 class="text-2xl font-semibold text-surface-100">Programs</h1>
    <p class="text-xs text-surface-500">
      Multi-week training plans built from peer-reviewed exercise science.
    </p>
  </div>

  {#if error}
    <div class="p-4 rounded-xl bg-red-500/10 border border-red-500/30">
      <p class="text-sm text-red-400">{error}</p>
    </div>
  {/if}

  <!-- Build-your-own quiz CTA -->
  <a
    href="/programs/quiz"
    class="block p-5 rounded-2xl bg-gradient-to-br from-primary-500/20 to-primary-600/5 border border-primary-500/30 hover:border-primary-500/50 transition-colors"
  >
    <div class="flex items-center justify-between gap-3">
      <div>
        <p class="text-base font-semibold text-surface-100">Build my program</p>
        <p class="mt-0.5 text-xs text-surface-400">
          Answer a few questions — goal, days, experience — and we generate it.
        </p>
      </div>
      <svg class="w-6 h-6 text-primary-300 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
      </svg>
    </div>
  </a>

  {#if loading}
    <div class="space-y-2">
      {#each Array(4) as _}
        <div class="h-28 bg-surface-800 rounded-xl border border-surface-700 animate-pulse"></div>
      {/each}
    </div>
  {:else}
    <!-- The user's active Program -->
    {#if activeProgram}
      <section class="space-y-2">
        <h2 class="text-xs font-semibold uppercase tracking-wide text-surface-500">Your active program</h2>
        <a
          href="/programs/{activeProgram.id}"
          class="block p-4 rounded-xl bg-surface-800 border border-primary-500/40"
        >
          <div class="flex items-center justify-between gap-3">
            <div class="min-w-0">
              <p class="text-sm font-semibold text-surface-100 truncate">{activeProgram.name}</p>
              <p class="mt-0.5 text-xs text-surface-400">
                {activeProgram.days_per_week} days/week · {activeProgram.total_weeks} weeks ·
                {goalLabel[activeProgram.goal] ?? activeProgram.goal}
              </p>
            </div>
            <span class="shrink-0 px-2 py-0.5 rounded-full bg-primary-500/20 text-primary-300 text-[10px] font-semibold uppercase">
              Active
            </span>
          </div>
        </a>
      </section>
    {/if}

    <!-- Preset catalog -->
    <section class="space-y-2">
      <h2 class="text-xs font-semibold uppercase tracking-wide text-surface-500">Preset programs</h2>
      <ul class="space-y-2">
        {#each presets as preset (preset.key)}
          <li class="p-4 rounded-xl bg-surface-800 border border-surface-700">
            <p class="text-sm font-semibold text-surface-100">{preset.name}</p>
            <p class="mt-1 text-xs text-surface-400 leading-relaxed">{preset.summary}</p>
            <div class="mt-2 flex items-center gap-2 text-[11px] text-surface-500">
              <span class="px-1.5 py-0.5 rounded bg-surface-700">{goalLabel[preset.goal] ?? preset.goal}</span>
              <span class="px-1.5 py-0.5 rounded bg-surface-700">{preset.days_per_week} days/week</span>
              <span class="px-1.5 py-0.5 rounded bg-surface-700 capitalize">{preset.experience}</span>
            </div>
            <button
              onclick={() => startPreset(preset.key)}
              disabled={generatingKey !== null}
              class="mt-3 w-full py-2.5 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-semibold transition-colors disabled:opacity-50"
            >
              {#if generatingKey === preset.key}
                Generating…
              {:else}
                Use this program
              {/if}
            </button>
          </li>
        {/each}
      </ul>
    </section>

    <!-- Archived Programs -->
    {#if archived.length > 0}
      <section class="space-y-2">
        <h2 class="text-xs font-semibold uppercase tracking-wide text-surface-500">Past programs</h2>
        <ul class="space-y-2">
          {#each archived as p (p.id)}
            <a
              href="/programs/{p.id}"
              class="block p-3 rounded-xl bg-surface-800/60 border border-surface-700/60"
            >
              <p class="text-sm font-medium text-surface-300 truncate">{p.name}</p>
              <p class="text-[11px] text-surface-500">{p.days_per_week} days/week · {p.total_weeks} weeks</p>
            </a>
          {/each}
        </ul>
      </section>
    {/if}
  {/if}
</div>
