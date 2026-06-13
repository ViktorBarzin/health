<script lang="ts">
  import { api } from '$lib/api';
  import { entryMacros, formatMacro, formatServing } from '$lib/nutrition';
  import type { DiaryEntry, Food, Meal } from '$lib/types';

  // A mobile bottom-sheet for adding (or editing) a Diary Entry: search the Food
  // catalog → pick a Food → set the quantity (servings) and Meal → save.
  // Server-side Food search, debounced. On edit, it opens pre-seeded on the
  // quantity step for the entry's existing Food/quantity/meal.
  let {
    open = false,
    date,
    defaultMeal = 'breakfast',
    edit = null,
    onsaved,
    onclose,
  }: {
    open?: boolean;
    /** The day (YYYY-MM-DD) a newly-added entry lands on. */
    date: string;
    /** Which Meal a fresh add defaults to (the section the user tapped "+"). */
    defaultMeal?: Meal;
    /** When set, the sheet edits this entry instead of creating a new one. */
    edit?: DiaryEntry | null;
    onsaved: () => void;
    onclose: () => void;
  } = $props();

  const MEALS: Meal[] = ['breakfast', 'lunch', 'dinner', 'snack'];

  // Two steps: 'search' (pick a Food) → 'detail' (quantity + meal).
  let step = $state<'search' | 'detail'>('search');
  let foods = $state<Food[]>([]);
  let search = $state('');
  let loading = $state(false);
  let error = $state('');

  let selected = $state<Food | null>(null);
  let quantity = $state(1);
  let meal = $state<Meal>('breakfast');
  let saving = $state(false);

  // Seed the sheet each time it opens: edit → jump to the detail step with the
  // entry's Food/quantity/meal; add → start at search in the tapped Meal.
  let seeded = $state(false);
  $effect(() => {
    if (open && !seeded) {
      seeded = true;
      if (edit) {
        selected = {
          id: edit.food_id,
          name: edit.food_name,
          brand: edit.brand,
          serving_size: edit.serving_size,
          serving_unit: edit.serving_unit,
          // Per-serving macros recovered from the entry (macros ÷ quantity).
          calories: edit.quantity ? edit.calories / edit.quantity : 0,
          protein_g: edit.quantity ? edit.protein_g / edit.quantity : 0,
          carbs_g: edit.quantity ? edit.carbs_g / edit.quantity : 0,
          fat_g: edit.quantity ? edit.fat_g / edit.quantity : 0,
          is_custom: false,
          source: '',
        };
        quantity = edit.quantity;
        meal = edit.meal;
        step = 'detail';
      } else {
        selected = null;
        quantity = 1;
        meal = defaultMeal;
        step = 'search';
        search = '';
      }
      error = '';
    } else if (!open && seeded) {
      seeded = false;
    }
  });

  // Search the catalog whenever the query changes while on the search step.
  let debounce: ReturnType<typeof setTimeout>;
  $effect(() => {
    if (!open || step !== 'search') return;
    const _s = search;
    clearTimeout(debounce);
    debounce = setTimeout(() => loadFoods(), 200);
    return () => clearTimeout(debounce);
  });

  async function loadFoods() {
    loading = true;
    error = '';
    try {
      const params = new URLSearchParams({ limit: '50' });
      if (search.trim()) params.set('search', search.trim());
      foods = await api.get<Food[]>(`/api/nutrition/foods?${params}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load foods';
    } finally {
      loading = false;
    }
  }

  function pickFood(f: Food) {
    selected = f;
    quantity = 1;
    step = 'detail';
  }

  function stepQuantity(delta: number) {
    quantity = Math.max(0.1, Math.round((quantity + delta) * 100) / 100);
  }

  // Live macro preview for the chosen Food at the current quantity.
  let preview = $derived(
    selected
      ? entryMacros(selected, quantity)
      : { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
  );

  let canSave = $derived(!!selected && quantity > 0 && !saving);

  async function save() {
    if (!canSave || !selected) return;
    saving = true;
    error = '';
    try {
      if (edit) {
        await api.patch<DiaryEntry>(`/api/nutrition/entries/${edit.id}`, {
          food_id: selected.id,
          meal,
          quantity,
        });
      } else {
        await api.post<DiaryEntry>('/api/nutrition/entries', {
          food_id: selected.id,
          entry_date: date,
          meal,
          quantity,
        });
      }
      onsaved();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to save entry';
      saving = false;
    }
  }

  function mealLabel(m: Meal): string {
    return m.charAt(0).toUpperCase() + m.slice(1);
  }
</script>

{#if open}
  <button class="fixed inset-0 bg-black/60 z-40" onclick={onclose} aria-label="Close"></button>
  <div
    class="fixed bottom-0 inset-x-0 z-50 bg-surface-900 border-t border-surface-700
           rounded-t-2xl pb-[env(safe-area-inset-bottom)] shadow-2xl flex flex-col"
    style="max-height: 85vh;"
    role="dialog"
    aria-label={edit ? 'Edit diary entry' : 'Add food'}
  >
    <div class="mx-auto my-2 h-1 w-10 rounded-full bg-surface-600 shrink-0"></div>

    <div class="px-4 pb-3 shrink-0">
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          {#if step === 'detail' && !edit}
            <button onclick={() => (step = 'search')} class="text-surface-400 hover:text-surface-200 p-1" aria-label="Back">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
              </svg>
            </button>
          {/if}
          <h2 class="text-base font-semibold text-surface-100">
            {edit ? 'Edit entry' : step === 'search' ? 'Add food' : selected?.name}
          </h2>
        </div>
        <button onclick={onclose} class="text-surface-400 hover:text-surface-200 p-1" aria-label="Close">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {#if step === 'search'}
        <div class="relative">
          <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-surface-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
          </svg>
          <!-- svelte-ignore a11y_autofocus -->
          <input
            type="text"
            bind:value={search}
            autofocus
            placeholder="Search foods…"
            class="w-full pl-10 pr-4 py-2.5 bg-surface-800 border border-surface-700 rounded-lg
                   text-surface-100 placeholder-surface-500 text-base
                   focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 transition-colors"
          />
        </div>
      {/if}
    </div>

    <div class="flex-1 overflow-y-auto px-4 pb-4">
      {#if error}
        <p class="text-sm text-red-400 py-2">{error}</p>
      {/if}

      {#if step === 'search'}
        {#if loading && foods.length === 0}
          <div class="space-y-2">
            {#each Array(6) as _}
              <div class="h-14 bg-surface-800 rounded-lg animate-pulse"></div>
            {/each}
          </div>
        {:else if foods.length === 0}
          <p class="text-sm text-surface-500 py-8 text-center">No foods found.</p>
        {:else}
          <ul class="space-y-1.5">
            {#each foods as f (f.id)}
              <li>
                <button
                  onclick={() => pickFood(f)}
                  class="w-full flex items-center gap-3 p-2.5 rounded-lg text-left
                         bg-surface-800 border border-surface-700 hover:border-primary-500/50 hover:bg-surface-800/80 transition-all"
                >
                  <div class="min-w-0 flex-1">
                    <p class="text-sm font-medium text-surface-200 truncate">{f.name}</p>
                    <p class="text-xs text-surface-500 truncate">
                      {formatMacro(f.calories, 'calories')} kcal · {f.serving_size} {f.serving_unit}
                      {#if f.brand}· {f.brand}{/if}
                    </p>
                  </div>
                  {#if f.is_custom}
                    <span class="shrink-0 text-[0.55rem] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-primary-500/15 text-primary-300">Custom</span>
                  {/if}
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      {:else if selected}
        <!-- Quantity stepper -->
        <div class="mb-5">
          <p class="text-sm font-medium text-surface-300 mb-2">Servings</p>
          <div class="flex items-center justify-center gap-3">
            <button onclick={() => stepQuantity(-0.5)} class="w-11 h-11 rounded-lg bg-surface-800 border border-surface-700 text-surface-200 text-2xl font-medium hover:bg-surface-700" aria-label="Less">−</button>
            <input
              type="number"
              inputmode="decimal"
              step="0.5"
              min="0.1"
              bind:value={quantity}
              class="w-24 text-center py-2.5 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 text-2xl font-bold focus:outline-none focus:border-primary-500"
              aria-label="Number of servings"
            />
            <button onclick={() => stepQuantity(0.5)} class="w-11 h-11 rounded-lg bg-surface-800 border border-surface-700 text-surface-200 text-2xl font-medium hover:bg-surface-700" aria-label="More">+</button>
          </div>
          <p class="mt-2 text-center text-xs text-surface-500">
            {formatServing(quantity, selected.serving_size, selected.serving_unit)}
            · 1 serving = {selected.serving_size} {selected.serving_unit}
          </p>
        </div>

        <!-- Meal picker -->
        <div class="mb-5">
          <p class="text-sm font-medium text-surface-300 mb-2">Meal</p>
          <div class="grid grid-cols-4 gap-2">
            {#each MEALS as m}
              <button
                onclick={() => (meal = m)}
                class="py-2 rounded-lg text-xs font-medium capitalize transition-colors border
                       {meal === m
                  ? 'bg-primary-500/20 border-primary-500/60 text-primary-200'
                  : 'bg-surface-800 border-surface-700 text-surface-400 hover:text-surface-200'}"
              >
                {mealLabel(m)}
              </button>
            {/each}
          </div>
        </div>

        <!-- Live macro preview -->
        <div class="grid grid-cols-4 gap-2 mb-5">
          <div class="text-center p-2 rounded-lg bg-surface-800 border border-surface-700">
            <p class="text-base font-bold text-surface-100">{formatMacro(preview.calories, 'calories')}</p>
            <p class="text-[0.6rem] uppercase tracking-wide text-surface-500">kcal</p>
          </div>
          <div class="text-center p-2 rounded-lg bg-surface-800 border border-surface-700">
            <p class="text-base font-bold text-blue-300">{formatMacro(preview.protein_g, 'protein_g')}</p>
            <p class="text-[0.6rem] uppercase tracking-wide text-surface-500">Protein</p>
          </div>
          <div class="text-center p-2 rounded-lg bg-surface-800 border border-surface-700">
            <p class="text-base font-bold text-emerald-300">{formatMacro(preview.carbs_g, 'carbs_g')}</p>
            <p class="text-[0.6rem] uppercase tracking-wide text-surface-500">Carbs</p>
          </div>
          <div class="text-center p-2 rounded-lg bg-surface-800 border border-surface-700">
            <p class="text-base font-bold text-amber-300">{formatMacro(preview.fat_g, 'fat_g')}</p>
            <p class="text-[0.6rem] uppercase tracking-wide text-surface-500">Fat</p>
          </div>
        </div>

        <button
          onclick={save}
          disabled={!canSave}
          class="w-full py-3 px-4 bg-primary-500 hover:bg-primary-600 text-white font-semibold rounded-lg
                 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {#if saving}
            <span class="inline-flex items-center gap-2">
              <div class="w-4 h-4 border-2 border-white/50 border-t-transparent rounded-full animate-spin"></div>
              Saving…
            </span>
          {:else}
            {edit ? 'Save changes' : 'Add to diary'}
          {/if}
        </button>
      {/if}
    </div>
  </div>
{/if}
