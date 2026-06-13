<script lang="ts">
  import { api } from '$lib/api';
  import AddEntrySheet from '$lib/components/nutrition/AddEntrySheet.svelte';
  import BudgetCard from '$lib/components/nutrition/BudgetCard.svelte';
  import { MACRO_SERIES, formatMacro, formatServing, macroCalorieSplit } from '$lib/nutrition';
  import type { DiaryDay, DiaryEntry, Meal } from '$lib/types';

  // The Nutrition day view (the MyFitnessPal core, #21): the four Meals with
  // their entries, per-meal subtotals, and a running daily total. Tap "+" on a
  // Meal to add a Food; tap an entry to edit; delete from the edit row. Mobile-
  // first. A Diary Entry belongs to a calendar day, so the date is a YYYY-MM-DD
  // string handled without timezone math.

  const MEAL_ORDER: Meal[] = ['breakfast', 'lunch', 'dinner', 'snack'];

  let date = $state(todayIso());
  let day = $state<DiaryDay | null>(null);
  let loading = $state(true);
  let error = $state('');

  // Add/edit sheet state.
  let sheetOpen = $state(false);
  let sheetMeal = $state<Meal>('breakfast');
  let editing = $state<DiaryEntry | null>(null);

  function todayIso(): string {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  /** Shift a YYYY-MM-DD string by N days (timezone-safe, calendar arithmetic). */
  function shiftIso(iso: string, days: number): string {
    const [y, m, d] = iso.split('-').map(Number);
    const dt = new Date(Date.UTC(y, m - 1, d));
    dt.setUTCDate(dt.getUTCDate() + days);
    return dt.toISOString().slice(0, 10);
  }

  function prettyDate(iso: string): string {
    const [y, m, d] = iso.split('-').map(Number);
    const dt = new Date(Date.UTC(y, m - 1, d));
    if (iso === todayIso()) return 'Today';
    if (iso === shiftIso(todayIso(), -1)) return 'Yesterday';
    return dt.toLocaleDateString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC',
    });
  }

  let isToday = $derived(date === todayIso());

  // Reload the day whenever the date changes.
  $effect(() => {
    const _d = date;
    load();
  });

  async function load() {
    loading = true;
    error = '';
    try {
      day = await api.get<DiaryDay>(`/api/nutrition/diary?date=${date}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load diary';
    } finally {
      loading = false;
    }
  }

  function sectionFor(meal: Meal) {
    return day?.meals.find((m) => m.meal === meal);
  }

  function openAdd(meal: Meal) {
    editing = null;
    sheetMeal = meal;
    sheetOpen = true;
  }

  function openEdit(entry: DiaryEntry) {
    editing = entry;
    sheetOpen = true;
  }

  function onSaved() {
    sheetOpen = false;
    editing = null;
    load();
  }

  async function deleteEntry(entry: DiaryEntry) {
    // Optimistic: drop it from view, then reconcile from the server.
    try {
      await api.delete(`/api/nutrition/entries/${entry.id}`);
      load();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to delete entry';
    }
  }

  let split = $derived(day ? macroCalorieSplit(day.total) : null);

  function mealLabel(m: Meal): string {
    return m.charAt(0).toUpperCase() + m.slice(1);
  }
</script>

<div class="space-y-4 pb-24">
  <!-- Header: date stepper + history link -->
  <div class="flex items-center justify-between">
    <h1 class="text-2xl font-semibold text-surface-100">Nutrition</h1>
    <a
      href="/nutrition/history"
      class="inline-flex items-center gap-1.5 px-3 py-2 text-sm text-surface-400 hover:text-surface-200 transition-colors"
    >
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z" />
      </svg>
      History
    </a>
  </div>

  <div class="flex items-center justify-between bg-surface-800 rounded-xl border border-surface-700 px-2 py-1.5">
    <button onclick={() => (date = shiftIso(date, -1))} class="p-2 text-surface-400 hover:text-surface-200" aria-label="Previous day">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
      </svg>
    </button>
    <div class="text-center">
      <p class="text-sm font-semibold text-surface-100">{prettyDate(date)}</p>
      {#if !isToday}
        <button onclick={() => (date = todayIso())} class="text-[0.65rem] text-primary-400 hover:text-primary-300">Jump to today</button>
      {/if}
    </div>
    <button
      onclick={() => (date = shiftIso(date, 1))}
      disabled={isToday}
      class="p-2 text-surface-400 hover:text-surface-200 disabled:opacity-30"
      aria-label="Next day"
    >
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
      </svg>
    </button>
  </div>

  {#if error}
    <div class="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-red-400 text-sm">{error}</p>
      <button class="mt-2 px-4 py-1.5 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm" onclick={load}>Retry</button>
    </div>
  {/if}

  <!-- Daily total card -->
  {#if loading && !day}
    <div class="h-28 bg-surface-800 rounded-xl border border-surface-700 animate-pulse"></div>
  {:else if day}
    <div class="bg-surface-800 rounded-xl border border-surface-700 p-4">
      <div class="flex items-end justify-between">
        <div>
          <p class="text-xs uppercase tracking-wide text-surface-500">Total today</p>
          <p class="text-3xl font-bold text-surface-100">{formatMacro(day.total.calories, 'calories')}<span class="text-base font-normal text-surface-500"> kcal</span></p>
        </div>
        <div class="flex gap-4 text-right">
          <div>
            <p class="text-sm font-semibold text-blue-300">{formatMacro(day.total.protein_g, 'protein_g')}</p>
            <p class="text-[0.6rem] uppercase tracking-wide text-surface-500">Protein</p>
          </div>
          <div>
            <p class="text-sm font-semibold text-emerald-300">{formatMacro(day.total.carbs_g, 'carbs_g')}</p>
            <p class="text-[0.6rem] uppercase tracking-wide text-surface-500">Carbs</p>
          </div>
          <div>
            <p class="text-sm font-semibold text-amber-300">{formatMacro(day.total.fat_g, 'fat_g')}</p>
            <p class="text-[0.6rem] uppercase tracking-wide text-surface-500">Fat</p>
          </div>
        </div>
      </div>
      <!-- Macro split bar -->
      {#if split && day.total.calories > 0}
        <div class="mt-3 flex h-2 overflow-hidden rounded-full bg-surface-700">
          {#each MACRO_SERIES as s}
            {@const pct = split[s.key].pct}
            {#if pct > 0}
              <div style="width: {pct}%; background: {s.color};" title="{s.label} {pct.toFixed(0)}%"></div>
            {/if}
          {/each}
        </div>
      {/if}
    </div>

    <!-- Budget: the Goal-driven daily target vs logged + the weight trend (#23).
         Shown for today only — the target/trend are computed as of now, so pairing
         them with a past day's logged total would mislead. -->
    {#if isToday}
      <BudgetCard logged={day.total} />
    {/if}

    <!-- The four Meal sections -->
    {#each MEAL_ORDER as meal (meal)}
      {@const section = sectionFor(meal)}
      <div class="bg-surface-800 rounded-xl border border-surface-700 overflow-hidden">
        <div class="flex items-center justify-between px-4 py-2.5 border-b border-surface-700/60">
          <div class="flex items-baseline gap-2">
            <h2 class="text-sm font-semibold text-surface-200">{mealLabel(meal)}</h2>
            {#if section && section.totals.calories > 0}
              <span class="text-xs text-surface-500">{formatMacro(section.totals.calories, 'calories')} kcal</span>
            {/if}
          </div>
          <button
            onclick={() => openAdd(meal)}
            class="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium text-primary-300 hover:text-primary-200 hover:bg-primary-500/10 rounded-md transition-colors"
            aria-label="Add food to {meal}"
          >
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
            Add
          </button>
        </div>

        {#if section && section.entries.length > 0}
          <ul class="divide-y divide-surface-700/40">
            {#each section.entries as entry (entry.id)}
              <li class="flex items-center gap-2 px-4 py-2.5">
                <button onclick={() => openEdit(entry)} class="min-w-0 flex-1 text-left">
                  <p class="text-sm text-surface-200 truncate">{entry.food_name}</p>
                  <p class="text-xs text-surface-500">
                    {formatServing(entry.quantity, entry.serving_size, entry.serving_unit)}
                    · {formatMacro(entry.protein_g, 'protein_g')} P
                    · {formatMacro(entry.carbs_g, 'carbs_g')} C
                    · {formatMacro(entry.fat_g, 'fat_g')} F
                  </p>
                </button>
                <span class="shrink-0 text-sm font-medium text-surface-300 tabular-nums">{formatMacro(entry.calories, 'calories')}</span>
                <button
                  onclick={() => deleteEntry(entry)}
                  class="shrink-0 p-1.5 text-surface-500 hover:text-red-400 transition-colors"
                  aria-label="Delete {entry.food_name}"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                  </svg>
                </button>
              </li>
            {/each}
          </ul>
        {:else}
          <button onclick={() => openAdd(meal)} class="w-full px-4 py-3 text-left text-xs text-surface-600 hover:text-surface-400 transition-colors">
            No food logged — tap to add
          </button>
        {/if}
      </div>
    {/each}
  {/if}
</div>

<AddEntrySheet
  open={sheetOpen}
  {date}
  defaultMeal={sheetMeal}
  edit={editing}
  onsaved={onSaved}
  onclose={() => { sheetOpen = false; editing = null; }}
/>
