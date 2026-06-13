<script lang="ts">
  import { page } from '$app/stores';
  import { api } from '$lib/api';
  import { muscleLabel } from '$lib/muscle-heat';
  import {
    barHeightPct,
    formatProvenanceValue,
    groupVolumeByMuscle,
    maxTargetSets,
    provenanceReceipts,
  } from '$lib/program';
  import type { ProgramDetail } from '$lib/types';

  // Program overview (#13, ADR-0004): the weeks × days structure, the ramping
  // per-muscle weekly volume (a small bar strip), the deload week flagged, and
  // every derived number with its source Principle — the receipt stub the #14
  // receipts UI will expand into full citations. Plus a CTA into today's workout
  // (the active Program drives the daily Recommendation).
  let program = $state<ProgramDetail | null>(null);
  let loading = $state(true);
  let error = $state('');
  let acting = $state(false);

  let id = $derived($page.params.id);

  $effect(() => {
    if (id) load(id);
  });

  async function load(programId: string) {
    loading = true;
    error = '';
    try {
      program = await api.get<ProgramDetail>(`/api/programs/${programId}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load program';
    } finally {
      loading = false;
    }
  }

  async function activate() {
    if (!program || acting) return;
    acting = true;
    try {
      program = await api.post<ProgramDetail>(`/api/programs/${program.id}/activate`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to activate';
    } finally {
      acting = false;
    }
  }

  // The ramp strips, the bar scale, the week axis, and the provenance receipts —
  // all via the pure (unit-tested) helpers in $lib/program.
  let volumeSeries = $derived(groupVolumeByMuscle(program?.muscle_volumes ?? []));
  let maxSets = $derived(maxTargetSets(program?.muscle_volumes ?? []));
  let weeks = $derived(
    program ? Array.from({ length: program.total_weeks }, (_, i) => i + 1) : [],
  );
  let receipts = $derived(provenanceReceipts(program?.provenance ?? {}));

  const goalLabel: Record<string, string> = {
    bulk: 'Build muscle',
    cut: 'Lose fat',
    maintain: 'Maintain',
    strength: 'Get stronger',
  };
</script>

<div class="space-y-6 pb-24">
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
    <h1 class="text-xl font-semibold text-surface-100 truncate">
      {program?.name ?? 'Program'}
    </h1>
  </div>

  {#if error}
    <div class="p-4 rounded-xl bg-red-500/10 border border-red-500/30">
      <p class="text-sm text-red-400">{error}</p>
    </div>
  {/if}

  {#if loading}
    <div class="space-y-2">
      {#each Array(5) as _}
        <div class="h-20 bg-surface-800 rounded-xl border border-surface-700 animate-pulse"></div>
      {/each}
    </div>
  {:else if program}
    <!-- Summary chips -->
    <div class="flex flex-wrap gap-2 text-[11px] text-surface-300">
      <span class="px-2 py-1 rounded-lg bg-surface-800 border border-surface-700">{goalLabel[program.goal] ?? program.goal}</span>
      <span class="px-2 py-1 rounded-lg bg-surface-800 border border-surface-700 capitalize">{program.experience}</span>
      <span class="px-2 py-1 rounded-lg bg-surface-800 border border-surface-700">{program.days_per_week} days/week</span>
      <span class="px-2 py-1 rounded-lg bg-surface-800 border border-surface-700">{program.total_weeks} weeks</span>
      <span class="px-2 py-1 rounded-lg bg-surface-800 border border-surface-700">{program.rep_range_low}–{program.rep_range_high} reps</span>
      <span class="px-2 py-1 rounded-lg bg-surface-800 border border-surface-700">{program.effort_rir} RIR</span>
    </div>

    {#if program.status === 'active'}
      <a
        href="/programs/today"
        class="block py-3.5 rounded-2xl bg-primary-500 hover:bg-primary-600 text-center text-white font-semibold transition-colors shadow-lg shadow-primary-500/20"
      >
        Today's workout
      </a>
    {:else}
      <button
        onclick={activate}
        disabled={acting}
        class="w-full py-3.5 rounded-2xl border border-primary-500/50 text-primary-200 font-semibold transition-colors hover:bg-primary-500/10 disabled:opacity-50"
      >
        {acting ? 'Activating…' : 'Make this my active program'}
      </button>
    {/if}

    <!-- The split -->
    <section class="space-y-2">
      <h2 class="text-xs font-semibold uppercase tracking-wide text-surface-500">The split</h2>
      <ul class="space-y-2">
        {#each program.days as day (day.day_index)}
          <li class="p-3 rounded-xl bg-surface-800 border border-surface-700">
            <p class="text-sm font-semibold text-surface-100">{day.name}</p>
            <p class="mt-1 text-xs text-surface-400">
              {day.slots.map((s) => muscleLabel(s.muscle)).join(' · ')}
            </p>
          </li>
        {/each}
      </ul>
    </section>

    <!-- Weekly volume ramp -->
    <section class="space-y-2">
      <h2 class="text-xs font-semibold uppercase tracking-wide text-surface-500">
        Weekly volume (sets per muscle)
      </h2>
      <p class="text-[11px] text-surface-500">
        Ramps up across the block, then drops on the deload week (week {program.deload_week}).
      </p>
      <div class="space-y-2">
        {#each volumeSeries as series (series.muscle)}
          <div class="flex items-center gap-2">
            <span class="w-20 shrink-0 text-[11px] text-surface-400 truncate">{muscleLabel(series.muscle)}</span>
            <div class="flex-1 flex items-end gap-1 h-10">
              {#each series.weeks as v (v.week)}
                <div
                  class="flex-1 rounded-t {v.is_deload ? 'bg-amber-500/70' : 'bg-primary-500/70'}"
                  style="height: {barHeightPct(v.target_sets, maxSets)}%"
                  title="Week {v.week}: {v.target_sets} sets{v.is_deload ? ' (deload)' : ''}"
                ></div>
              {/each}
            </div>
          </div>
        {/each}
      </div>
      <div class="flex items-center gap-3 text-[10px] text-surface-500 pl-22">
        {#each weeks as w (w)}
          <span class="flex-1 text-center">W{w}</span>
        {/each}
      </div>
    </section>

    <!-- Provenance receipts ("why this number") -->
    <section class="space-y-2">
      <h2 class="text-xs font-semibold uppercase tracking-wide text-surface-500">
        The science behind this plan
      </h2>
      <p class="text-[11px] text-surface-500">
        Every number is derived from the Principles knowledge base.
      </p>
      <ul class="space-y-1.5">
        {#each receipts as r (r.param)}
          <li class="flex items-center justify-between gap-3 px-3 py-2 rounded-lg bg-surface-800/60 border border-surface-700/60">
            <div class="min-w-0">
              <p class="text-xs text-surface-300 capitalize truncate">{r.label}</p>
              <a
                href="/principles/{r.principle_key}"
                class="text-[11px] text-primary-400 hover:text-primary-300 underline underline-offset-2"
              >
                {r.principle_key}
              </a>
            </div>
            <span class="shrink-0 text-sm font-semibold text-surface-100 tabular-nums">
              {formatProvenanceValue(r)}
            </span>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</div>
