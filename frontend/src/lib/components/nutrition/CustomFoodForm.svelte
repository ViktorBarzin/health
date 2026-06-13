<script lang="ts">
  import { api } from '$lib/api';
  import type { Food, FoodCreate } from '$lib/types';

  // Create a custom (private) Food with per-serving macros (#22). On success it
  // calls `oncreated` with the new Food so the add-entry flow can immediately log
  // it. Macros are entered PER SERVING (one serving = serving_size of the unit),
  // matching the catalog convention.

  let {
    oncreated,
    oncancel,
  }: {
    oncreated: (food: Food) => void;
    oncancel: () => void;
  } = $props();

  let name = $state('');
  let brand = $state('');
  let servingSize = $state(100);
  let servingUnit = $state('g');
  let calories = $state(0);
  let protein = $state(0);
  let carbs = $state(0);
  let fat = $state(0);
  let saving = $state(false);
  let error = $state('');

  let canSave = $derived(
    name.trim().length > 0 && servingSize > 0 && servingUnit.trim().length > 0 && !saving,
  );

  async function save() {
    if (!canSave) return;
    saving = true;
    error = '';
    const payload: FoodCreate = {
      name: name.trim(),
      brand: brand.trim() || null,
      serving_size: servingSize,
      serving_unit: servingUnit.trim(),
      calories,
      protein_g: protein,
      carbs_g: carbs,
      fat_g: fat,
    };
    try {
      const food = await api.post<Food>('/api/nutrition/foods', payload);
      oncreated(food);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to create food';
      saving = false;
    }
  }
</script>

<div class="space-y-4">
  {#if error}
    <p class="text-sm text-red-400">{error}</p>
  {/if}

  <div>
    <label for="cf-name" class="block text-xs font-medium text-surface-400 mb-1">Name</label>
    <input
      id="cf-name"
      type="text"
      bind:value={name}
      placeholder="e.g. Grandma's granola"
      class="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 placeholder-surface-500 text-base focus:outline-none focus:border-primary-500"
    />
  </div>

  <div>
    <label for="cf-brand" class="block text-xs font-medium text-surface-400 mb-1">Brand (optional)</label>
    <input
      id="cf-brand"
      type="text"
      bind:value={brand}
      class="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 text-base focus:outline-none focus:border-primary-500"
    />
  </div>

  <div class="grid grid-cols-2 gap-3">
    <div>
      <label for="cf-size" class="block text-xs font-medium text-surface-400 mb-1">Serving size</label>
      <input id="cf-size" type="number" inputmode="decimal" min="0.1" step="any" bind:value={servingSize}
        class="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 text-base focus:outline-none focus:border-primary-500" />
    </div>
    <div>
      <label for="cf-unit" class="block text-xs font-medium text-surface-400 mb-1">Unit</label>
      <input id="cf-unit" type="text" bind:value={servingUnit} placeholder="g, ml, slice…"
        class="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 text-base focus:outline-none focus:border-primary-500" />
    </div>
  </div>

  <div>
    <p class="text-xs font-medium text-surface-400 mb-1">Macros per serving</p>
    <div class="grid grid-cols-4 gap-2">
      <label class="block">
        <span class="block text-[0.6rem] uppercase tracking-wide text-surface-500 mb-1">kcal</span>
        <input type="number" inputmode="decimal" min="0" step="any" bind:value={calories}
          class="w-full px-2 py-2 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 text-center focus:outline-none focus:border-primary-500" />
      </label>
      <label class="block">
        <span class="block text-[0.6rem] uppercase tracking-wide text-blue-300 mb-1">Protein</span>
        <input type="number" inputmode="decimal" min="0" step="any" bind:value={protein}
          class="w-full px-2 py-2 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 text-center focus:outline-none focus:border-primary-500" />
      </label>
      <label class="block">
        <span class="block text-[0.6rem] uppercase tracking-wide text-emerald-300 mb-1">Carbs</span>
        <input type="number" inputmode="decimal" min="0" step="any" bind:value={carbs}
          class="w-full px-2 py-2 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 text-center focus:outline-none focus:border-primary-500" />
      </label>
      <label class="block">
        <span class="block text-[0.6rem] uppercase tracking-wide text-amber-300 mb-1">Fat</span>
        <input type="number" inputmode="decimal" min="0" step="any" bind:value={fat}
          class="w-full px-2 py-2 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 text-center focus:outline-none focus:border-primary-500" />
      </label>
    </div>
  </div>

  <div class="flex gap-2 pt-1">
    <button onclick={oncancel} class="flex-1 py-3 rounded-lg bg-surface-800 border border-surface-700 text-surface-300 hover:bg-surface-700">Cancel</button>
    <button onclick={save} disabled={!canSave}
      class="flex-1 py-3 rounded-lg bg-primary-500 hover:bg-primary-600 text-white font-semibold disabled:opacity-50 disabled:cursor-not-allowed">
      {saving ? 'Saving…' : 'Create & use'}
    </button>
  </div>
</div>
