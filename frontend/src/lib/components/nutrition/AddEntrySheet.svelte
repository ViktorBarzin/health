<script lang="ts">
  import { api } from '$lib/api';
  import BarcodeScanner from '$lib/components/nutrition/BarcodeScanner.svelte';
  import CustomFoodForm from '$lib/components/nutrition/CustomFoodForm.svelte';
  import RecipeBuilder from '$lib/components/nutrition/RecipeBuilder.svelte';
  import { entryMacros, formatMacro, formatServing } from '$lib/nutrition';
  import type { DiaryEntry, Food, Meal, Recipe } from '$lib/types';

  // A mobile bottom-sheet for adding (or editing) a Diary Entry. Several ways to
  // pick a Food, all converging on the quantity + Meal "detail" step:
  //   - search the catalog (server-side, debounced) — the default;
  //   - SCAN a barcode (#22): native BarcodeDetector / @zxing fallback → resolve
  //     via Open Food Facts (cached) → log; graceful fallback to search/manual;
  //   - create a custom Food (#22), private to the user;
  //   - build a Recipe (#22) — a Food composed of other Foods, computed macros.
  // On edit, it opens pre-seeded on the detail step for the entry's Food.
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

  // Steps: pick a Food ('search' | 'scan' | 'custom' | 'recipe') → 'detail'.
  type Step = 'search' | 'scan' | 'custom' | 'recipe' | 'detail';
  let step = $state<Step>('search');
  let foods = $state<Food[]>([]);
  let search = $state('');
  let loading = $state(false);
  let error = $state('');
  let scanMessage = $state('');

  let selected = $state<Food | null>(null);
  let quantity = $state(1);
  let meal = $state<Meal>('breakfast');
  let saving = $state(false);

  // Seed the sheet each time it opens: edit → detail step; add → search.
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
      scanMessage = '';
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

  // --- Barcode scanning (#22) ---
  let resolving = $state(false);
  async function onBarcode(code: string) {
    if (resolving) return;
    resolving = true;
    scanMessage = 'Looking up product…';
    error = '';
    try {
      const food = await api.get<Food>(`/api/nutrition/barcode/${code}`);
      // Resolved + cached → straight to the quantity step.
      pickFood(food);
    } catch (err) {
      // Not found / incomplete macros → fall back to search/manual entry.
      const status = (err as { status?: number })?.status;
      scanMessage =
        status === 404
          ? 'No product found for that barcode. Search or add it manually.'
          : 'Could not look up that barcode. Search or add it manually.';
      step = 'search';
      search = '';
    } finally {
      resolving = false;
    }
  }

  function onScanFallback(reason: string) {
    // Camera unavailable / denied → drop back to search with a hint.
    scanMessage = reason;
    step = 'search';
  }

  // --- Custom Food / Recipe creation flow into the detail step ---
  function onCustomCreated(food: Food) {
    pickFood(food);
  }
  function onRecipeCreated(recipe: Recipe) {
    // A Recipe is loggable as its backing Food.
    pickFood({
      id: recipe.food_id,
      name: recipe.name,
      brand: null,
      serving_size: 1,
      serving_unit: 'serving',
      calories: recipe.calories,
      protein_g: recipe.protein_g,
      carbs_g: recipe.carbs_g,
      fat_g: recipe.fat_g,
      is_custom: true,
      source: 'recipe',
    });
  }

  function stepQuantity(delta: number) {
    quantity = Math.max(0.1, Math.round((quantity + delta) * 100) / 100);
  }

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

  function headerTitle(): string {
    if (edit) return 'Edit entry';
    if (step === 'detail') return selected?.name ?? 'Add food';
    if (step === 'scan') return 'Scan barcode';
    if (step === 'custom') return 'New custom food';
    if (step === 'recipe') return 'New recipe';
    return 'Add food';
  }
</script>

{#if open}
  <button class="fixed inset-0 bg-black/60 z-40" onclick={onclose} aria-label="Close"></button>
  <div
    class="fixed bottom-0 inset-x-0 z-50 bg-surface-900 border-t border-surface-700
           rounded-t-2xl pb-[env(safe-area-inset-bottom)] shadow-2xl flex flex-col"
    style="max-height: 88vh;"
    role="dialog"
    aria-label={edit ? 'Edit diary entry' : 'Add food'}
  >
    <div class="mx-auto my-2 h-1 w-10 rounded-full bg-surface-600 shrink-0"></div>

    <div class="px-4 pb-3 shrink-0">
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          {#if step !== 'search' && !edit}
            <button onclick={() => { step = 'search'; }} class="text-surface-400 hover:text-surface-200 p-1" aria-label="Back">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
              </svg>
            </button>
          {/if}
          <h2 class="text-base font-semibold text-surface-100">{headerTitle()}</h2>
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

        <!-- Quick actions: scan / custom / recipe -->
        <div class="grid grid-cols-3 gap-2 mt-2">
          <button onclick={() => { scanMessage = ''; step = 'scan'; }}
            class="flex flex-col items-center gap-1 py-2 rounded-lg bg-surface-800 border border-surface-700 text-surface-300 hover:border-primary-500/50 hover:text-primary-200">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v2.25M3.75 19.125c0 .621.504 1.125 1.125 1.125h2.25a1.125 1.125 0 001.125-1.125v-2.25M19.5 4.875c0-.621-.504-1.125-1.125-1.125h-2.25a1.125 1.125 0 00-1.125 1.125v2.25M19.5 19.125c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125v-2.25M8.25 12h7.5" /></svg>
            <span class="text-[0.65rem] font-medium">Scan</span>
          </button>
          <button onclick={() => { step = 'custom'; }}
            class="flex flex-col items-center gap-1 py-2 rounded-lg bg-surface-800 border border-surface-700 text-surface-300 hover:border-primary-500/50 hover:text-primary-200">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v6m3-3H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
            <span class="text-[0.65rem] font-medium">Custom</span>
          </button>
          <button onclick={() => { step = 'recipe'; }}
            class="flex flex-col items-center gap-1 py-2 rounded-lg bg-surface-800 border border-surface-700 text-surface-300 hover:border-primary-500/50 hover:text-primary-200">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M3 6.75A2.25 2.25 0 015.25 4.5h13.5A2.25 2.25 0 0121 6.75v10.5A2.25 2.25 0 0118.75 19.5H5.25A2.25 2.25 0 013 17.25V6.75zM7.5 8.25h9M7.5 12h9m-9 3.75h5.25" /></svg>
            <span class="text-[0.65rem] font-medium">Recipe</span>
          </button>
        </div>

        {#if scanMessage}
          <p class="mt-2 text-xs text-amber-400">{scanMessage}</p>
        {/if}
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
                  {#if f.source === 'recipe'}
                    <span class="shrink-0 text-[0.55rem] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-300">Recipe</span>
                  {:else if f.is_custom}
                    <span class="shrink-0 text-[0.55rem] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-primary-500/15 text-primary-300">Custom</span>
                  {/if}
                </button>
              </li>
            {/each}
          </ul>
        {/if}
      {:else if step === 'scan'}
        <BarcodeScanner active={open && step === 'scan'} ondetected={onBarcode} onfallback={onScanFallback} />
        {#if resolving}
          <p class="mt-3 text-center text-sm text-primary-300">Looking up product…</p>
        {/if}
        <button onclick={() => { step = 'search'; }} class="mt-3 w-full py-2.5 rounded-lg bg-surface-800 border border-surface-700 text-sm text-surface-300 hover:bg-surface-700">
          Enter manually instead
        </button>
      {:else if step === 'custom'}
        <CustomFoodForm oncreated={onCustomCreated} oncancel={() => { step = 'search'; }} />
      {:else if step === 'recipe'}
        <RecipeBuilder oncreated={onRecipeCreated} oncancel={() => { step = 'search'; }} />
      {:else if step === 'detail' && selected}
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
