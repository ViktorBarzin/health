<script lang="ts">
  import { api } from '$lib/api';
  import { formatMacro } from '$lib/nutrition';
  import type { Food, Recipe, RecipeCreate } from '$lib/types';

  // Build a Recipe (#22): a name, a yield (servings the recipe makes), and a list
  // of ingredient Foods with quantities. Per-serving macros are COMPUTED
  // server-side (Σ ingredient macros ÷ yield); we show a live client-side preview
  // of the same arithmetic. On save it calls `oncreated` with the new Recipe so
  // the add-entry flow can log it (its `food_id` is a normal Food id).

  let {
    oncreated,
    oncancel,
  }: {
    oncreated: (recipe: Recipe) => void;
    oncancel: () => void;
  } = $props();

  interface Picked {
    food: Food;
    quantity: number;
  }

  let name = $state('');
  let yieldServings = $state(1);
  let ingredients = $state<Picked[]>([]);
  let saving = $state(false);
  let error = $state('');

  // Inline ingredient search.
  let search = $state('');
  let results = $state<Food[]>([]);
  let searching = $state(false);
  let debounce: ReturnType<typeof setTimeout>;

  $effect(() => {
    const _s = search;
    clearTimeout(debounce);
    if (!search.trim()) {
      results = [];
      return;
    }
    debounce = setTimeout(loadResults, 200);
    return () => clearTimeout(debounce);
  });

  async function loadResults() {
    searching = true;
    try {
      const params = new URLSearchParams({ limit: '30', search: search.trim() });
      results = await api.get<Food[]>(`/api/nutrition/foods?${params}`);
    } catch {
      results = [];
    } finally {
      searching = false;
    }
  }

  function addIngredient(food: Food) {
    if (!ingredients.some((i) => i.food.id === food.id)) {
      ingredients = [...ingredients, { food, quantity: 1 }];
    }
    search = '';
    results = [];
  }

  function removeIngredient(id: string) {
    ingredients = ingredients.filter((i) => i.food.id !== id);
  }

  function setQty(id: string, q: number) {
    ingredients = ingredients.map((i) =>
      i.food.id === id ? { ...i, quantity: Math.max(0.1, q) } : i,
    );
  }

  // Live preview: Σ (ingredient per-serving macros × quantity) ÷ yield.
  let perServing = $derived.by(() => {
    const y = yieldServings > 0 ? yieldServings : 1;
    const sum = ingredients.reduce(
      (acc, { food, quantity }) => ({
        calories: acc.calories + food.calories * quantity,
        protein_g: acc.protein_g + food.protein_g * quantity,
        carbs_g: acc.carbs_g + food.carbs_g * quantity,
        fat_g: acc.fat_g + food.fat_g * quantity,
      }),
      { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
    );
    return {
      calories: sum.calories / y,
      protein_g: sum.protein_g / y,
      carbs_g: sum.carbs_g / y,
      fat_g: sum.fat_g / y,
    };
  });

  let canSave = $derived(
    name.trim().length > 0 && yieldServings > 0 && ingredients.length > 0 && !saving,
  );

  async function save() {
    if (!canSave) return;
    saving = true;
    error = '';
    const payload: RecipeCreate = {
      name: name.trim(),
      yield_servings: yieldServings,
      ingredients: ingredients.map((i) => ({ food_id: i.food.id, quantity: i.quantity })),
    };
    try {
      const recipe = await api.post<Recipe>('/api/nutrition/recipes', payload);
      oncreated(recipe);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to create recipe';
      saving = false;
    }
  }
</script>

<div class="space-y-4">
  {#if error}
    <p class="text-sm text-red-400">{error}</p>
  {/if}

  <div class="grid grid-cols-3 gap-3">
    <div class="col-span-2">
      <label for="rb-name" class="block text-xs font-medium text-surface-400 mb-1">Recipe name</label>
      <input id="rb-name" type="text" bind:value={name} placeholder="e.g. Chicken & rice bowl"
        class="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 placeholder-surface-500 text-base focus:outline-none focus:border-primary-500" />
    </div>
    <div>
      <label for="rb-yield" class="block text-xs font-medium text-surface-400 mb-1">Servings</label>
      <input id="rb-yield" type="number" inputmode="decimal" min="0.1" step="any" bind:value={yieldServings}
        class="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 text-base focus:outline-none focus:border-primary-500" />
    </div>
  </div>

  <!-- Ingredient list -->
  <div>
    <p class="text-xs font-medium text-surface-400 mb-1">Ingredients</p>
    {#if ingredients.length > 0}
      <ul class="space-y-1.5 mb-2">
        {#each ingredients as ing (ing.food.id)}
          <li class="flex items-center gap-2 p-2 rounded-lg bg-surface-800 border border-surface-700">
            <span class="min-w-0 flex-1 truncate text-sm text-surface-200">{ing.food.name}</span>
            <input
              type="number" inputmode="decimal" min="0.1" step="any" value={ing.quantity}
              oninput={(e) => setQty(ing.food.id, parseFloat((e.target as HTMLInputElement).value) || 0)}
              class="w-16 px-2 py-1 bg-surface-900 border border-surface-700 rounded text-surface-100 text-center text-sm focus:outline-none focus:border-primary-500"
              aria-label="Servings of {ing.food.name}"
            />
            <span class="text-xs text-surface-500 w-10 shrink-0">×{ing.food.serving_size}{ing.food.serving_unit}</span>
            <button onclick={() => removeIngredient(ing.food.id)} class="p-1 text-surface-500 hover:text-red-400" aria-label="Remove {ing.food.name}">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
            </button>
          </li>
        {/each}
      </ul>
    {:else}
      <p class="text-xs text-surface-600 mb-2">No ingredients yet — search and add below.</p>
    {/if}

    <!-- Ingredient search -->
    <input
      type="text"
      bind:value={search}
      placeholder="Search foods to add…"
      class="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 placeholder-surface-500 text-base focus:outline-none focus:border-primary-500"
    />
    {#if search.trim()}
      <div class="mt-1.5 max-h-40 overflow-y-auto rounded-lg border border-surface-700 divide-y divide-surface-700/40">
        {#if searching}
          <p class="px-3 py-2 text-xs text-surface-500">Searching…</p>
        {:else if results.length === 0}
          <p class="px-3 py-2 text-xs text-surface-500">No foods found.</p>
        {:else}
          {#each results as f (f.id)}
            <button onclick={() => addIngredient(f)} class="w-full px-3 py-2 text-left text-sm text-surface-200 hover:bg-surface-700/50">
              {f.name}
              <span class="text-xs text-surface-500">· {formatMacro(f.calories, 'calories')} kcal / {f.serving_size}{f.serving_unit}</span>
            </button>
          {/each}
        {/if}
      </div>
    {/if}
  </div>

  <!-- Per-serving preview -->
  {#if ingredients.length > 0}
    <div class="rounded-lg bg-surface-800/60 border border-surface-700 p-3">
      <p class="text-[0.6rem] uppercase tracking-wide text-surface-500 mb-1">Per serving (computed)</p>
      <div class="grid grid-cols-4 gap-2 text-center">
        <div><p class="text-sm font-bold text-surface-100">{formatMacro(perServing.calories, 'calories')}</p><p class="text-[0.55rem] text-surface-500">kcal</p></div>
        <div><p class="text-sm font-bold text-blue-300">{formatMacro(perServing.protein_g, 'protein_g')}</p><p class="text-[0.55rem] text-surface-500">P</p></div>
        <div><p class="text-sm font-bold text-emerald-300">{formatMacro(perServing.carbs_g, 'carbs_g')}</p><p class="text-[0.55rem] text-surface-500">C</p></div>
        <div><p class="text-sm font-bold text-amber-300">{formatMacro(perServing.fat_g, 'fat_g')}</p><p class="text-[0.55rem] text-surface-500">F</p></div>
      </div>
    </div>
  {/if}

  <div class="flex gap-2">
    <button onclick={oncancel} class="flex-1 py-3 rounded-lg bg-surface-800 border border-surface-700 text-surface-300 hover:bg-surface-700">Cancel</button>
    <button onclick={save} disabled={!canSave}
      class="flex-1 py-3 rounded-lg bg-primary-500 hover:bg-primary-600 text-white font-semibold disabled:opacity-50 disabled:cursor-not-allowed">
      {saving ? 'Saving…' : 'Create & use'}
    </button>
  </div>
</div>
