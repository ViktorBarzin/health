<script lang="ts">
  import { api } from '$lib/api';
  import {
    budgetMacroTargets,
    goalLabel,
    remainingMacros,
    trendSummary,
  } from '$lib/budget';
  import { formatMacro } from '$lib/nutrition';
  import type { Budget, MacroTotals } from '$lib/types';

  // The Budget card (#23, ADR-0004): the Goal-driven, self-calibrating daily
  // calorie/macro target vs what's logged so far (remaining), plus the current
  // weight trend/rate. It self-loads the Budget (a server computation over the
  // user's intake + weight trend) and takes the day's *logged* totals as a prop so
  // "remaining" updates as the diary changes. Mobile-first; reuses formatMacro.

  let { logged }: { logged: MacroTotals } = $props();

  let budget = $state<Budget | null>(null);
  let loading = $state(true);

  $effect(() => {
    load();
  });

  async function load() {
    loading = true;
    try {
      budget = await api.get<Budget>('/api/nutrition/budget');
    } catch {
      budget = null;
    } finally {
      loading = false;
    }
  }

  let targets = $derived(budget ? budgetMacroTargets(budget) : null);
  let remaining = $derived(targets ? remainingMacros(targets, logged) : null);
  let trend = $derived(budget ? trendSummary(budget) : null);
  // Calorie progress (clamped 0–1); >1 means over budget.
  let calFrac = $derived(
    targets && targets.calories > 0 ? logged.calories / targets.calories : 0,
  );
  let over = $derived(calFrac > 1);

  const MACROS: { key: 'protein_g' | 'carbs_g' | 'fat_g'; label: string; color: string }[] = [
    { key: 'protein_g', label: 'Protein', color: '#60a5fa' },
    { key: 'carbs_g', label: 'Carbs', color: '#34d399' },
    { key: 'fat_g', label: 'Fat', color: '#fbbf24' },
  ];
</script>

<div class="rounded-xl bg-surface-800 border border-surface-700/50 p-4">
  <div class="flex items-center justify-between mb-3">
    <h3 class="text-sm font-semibold text-surface-200">Budget</h3>
    {#if budget && !budget.insufficient_data}
      <span class="text-[10px] text-surface-500 uppercase tracking-wide">
        {goalLabel(budget.goal)}
      </span>
    {/if}
  </div>

  {#if loading}
    <div class="space-y-2">
      <div class="h-8 w-32 bg-surface-700 rounded animate-pulse"></div>
      <div class="h-2 w-full bg-surface-700 rounded animate-pulse"></div>
    </div>
  {:else if !budget || budget.insufficient_data}
    <p class="text-xs text-surface-400 leading-relaxed">
      Not enough data for a calorie budget yet. Log your weight (a smart scale or a
      Connector) and a few days of food, and a Goal-driven target — calibrated to
      your real trend — appears here.
    </p>
  {:else if targets && remaining}
    <!-- Calorie target vs logged -->
    <div class="flex items-end justify-between">
      <div>
        <p class="text-3xl font-bold text-surface-100">
          {formatMacro(remaining.calories, 'calories')}<span class="text-base font-normal text-surface-500"> kcal left</span>
        </p>
        <p class="text-xs text-surface-500">
          {formatMacro(logged.calories, 'calories')} of {formatMacro(targets.calories, 'calories')} target
        </p>
      </div>
      {#if trend?.hasTrend}
        <div class="text-right">
          <p class="text-sm font-semibold text-surface-200">{trend.weightLabel}</p>
          {#if trend.rateLabel}
            <p class="text-[0.65rem] text-surface-400">{trend.rateLabel}</p>
          {/if}
        </div>
      {/if}
    </div>

    <!-- Calorie progress bar -->
    <div class="mt-3 h-2 overflow-hidden rounded-full bg-surface-700">
      <div
        class="h-full rounded-full transition-[width]"
        style="width: {Math.min(100, calFrac * 100)}%; background: {over ? '#f87171' : '#34d399'};"
      ></div>
    </div>

    <!-- Macro targets vs logged -->
    <div class="mt-3 grid grid-cols-3 gap-3">
      {#each MACROS as m}
        {@const t = targets[m.key]}
        {@const l = logged[m.key]}
        <div>
          <div class="flex items-baseline justify-between">
            <span class="text-[0.6rem] uppercase tracking-wide text-surface-500">{m.label}</span>
          </div>
          <p class="text-sm font-semibold" style="color: {m.color};">
            {formatMacro(remaining[m.key], m.key)}<span class="text-[0.6rem] font-normal text-surface-500"> left</span>
          </p>
          <div class="mt-1 h-1 overflow-hidden rounded-full bg-surface-700">
            <div
              class="h-full rounded-full"
              style="width: {t > 0 ? Math.min(100, (l / t) * 100) : 0}%; background: {m.color};"
            ></div>
          </div>
        </div>
      {/each}
    </div>

    <!-- Method footnote: be honest about an estimate vs a measured budget -->
    {#if budget.method === 'estimated'}
      <p class="mt-3 text-[0.65rem] text-surface-500 leading-relaxed">
        Estimated from your bodyweight — log a couple of weeks of food and weight
        and this calibrates to your measured trend.
      </p>
    {/if}
  {/if}
</div>
