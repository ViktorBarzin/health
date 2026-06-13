<script lang="ts">
  import { api } from '$lib/api';
  import { platesPerSide } from '$lib/plates';
  import type { GymProfile } from '$lib/types';
  import { formatWeight } from '$lib/utils/format';

  // Gym Profile editor (CONTEXT.md "Gym Profile"): the user's bar(s), plate
  // denominations, and general equipment. Drives the plate calculator now and
  // the Recommendation engine (#11) later. Mobile-first chip lists with a live
  // plate-calculator preview so the user can sanity-check their inventory.

  let profile = $state<GymProfile | null>(null);
  let loading = $state(true);
  let saving = $state(false);
  let error = $state('');
  let savedFlash = $state(false);

  // Add-input buffers.
  let newBar = $state('');
  let newPlate = $state('');
  let newEquipment = $state('');

  // Live preview target for the plate calculator.
  let previewTarget = $state(100);

  // The common equipment kinds (free-exercise-db vocabulary) offered as quick-adds.
  const EQUIPMENT_SUGGESTIONS = [
    'barbell', 'dumbbell', 'machine', 'cable', 'kettlebells', 'bands',
    'body only', 'medicine ball', 'exercise ball', 'foam roll', 'e-z curl bar',
  ];

  $effect(() => {
    load();
  });

  async function load() {
    loading = true;
    error = '';
    try {
      profile = await api.get<GymProfile>('/api/gym-profile');
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load gym profile';
    } finally {
      loading = false;
    }
  }

  async function save() {
    if (!profile || saving) return;
    saving = true;
    error = '';
    try {
      profile = await api.put<GymProfile>('/api/gym-profile', {
        bar_weights_kg: profile.bar_weights_kg,
        plate_weights_kg: profile.plate_weights_kg,
        equipment: profile.equipment,
      });
      savedFlash = true;
      setTimeout(() => (savedFlash = false), 1500);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to save gym profile';
    } finally {
      saving = false;
    }
  }

  function addWeight(list: 'bar_weights_kg' | 'plate_weights_kg', raw: string) {
    if (!profile) return;
    const v = parseFloat(raw);
    if (Number.isNaN(v) || v <= 0) return;
    if (!profile[list].includes(v)) {
      profile[list] = [...profile[list], v].sort((a, b) => a - b);
    }
  }

  function removeWeight(list: 'bar_weights_kg' | 'plate_weights_kg', v: number) {
    if (!profile) return;
    profile[list] = profile[list].filter((x) => x !== v);
  }

  function addEquipment(raw: string) {
    if (!profile) return;
    const s = raw.trim();
    if (!s) return;
    if (!profile.equipment.some((e) => e.toLowerCase() === s.toLowerCase())) {
      profile.equipment = [...profile.equipment, s];
    }
  }

  function removeEquipment(v: string) {
    if (!profile) return;
    profile.equipment = profile.equipment.filter((x) => x !== v);
  }

  // Live plate-calculator preview against the user's heaviest bar (their
  // standard barbell — the list is sorted ascending, so [0] is the lightest).
  let preview = $derived.by(() => {
    if (!profile || profile.bar_weights_kg.length === 0) return null;
    return platesPerSide(previewTarget, {
      bar: Math.max(...profile.bar_weights_kg),
      plates: profile.plate_weights_kg,
    });
  });
</script>

<div class="bg-surface-800 rounded-xl border border-surface-700 p-6 space-y-6">
  {#if loading}
    <div class="space-y-3 animate-pulse">
      <div class="w-1/3 h-4 bg-surface-700 rounded"></div>
      <div class="h-10 bg-surface-700/60 rounded"></div>
    </div>
  {:else if error && !profile}
    <div class="text-center">
      <p class="text-red-400 text-sm">{error}</p>
      <button class="mt-3 px-4 py-2 bg-red-500/20 hover:bg-red-500/30 text-red-300 rounded-lg text-sm" onclick={load}>Retry</button>
    </div>
  {:else if profile}
    <!-- Bars -->
    <div>
      <h4 class="text-sm font-medium text-surface-200">Bars</h4>
      <p class="text-xs text-surface-500 mt-0.5">The bar(s) you load, in kg.</p>
      <div class="flex flex-wrap gap-2 mt-3">
        {#each profile.bar_weights_kg as w (w)}
          <span class="inline-flex items-center gap-1.5 pl-3 pr-1.5 py-1 rounded-full bg-surface-700 text-surface-200 text-sm">
            {formatWeight(w)} kg
            <button onclick={() => removeWeight('bar_weights_kg', w)} class="w-5 h-5 rounded-full hover:bg-surface-600 text-surface-400 hover:text-surface-200 flex items-center justify-center" aria-label="Remove {w} kg bar">×</button>
          </span>
        {/each}
      </div>
      <form class="flex gap-2 mt-3" onsubmit={(e) => { e.preventDefault(); addWeight('bar_weights_kg', newBar); newBar = ''; }}>
        <input type="number" inputmode="decimal" step="0.5" bind:value={newBar} placeholder="e.g. 20" class="w-28 px-3 py-1.5 bg-surface-900 border border-surface-700 rounded-lg text-surface-100 text-sm focus:outline-none focus:border-primary-500" aria-label="New bar weight in kg" />
        <button type="submit" class="px-3 py-1.5 rounded-lg bg-surface-700 hover:bg-surface-600 text-surface-200 text-sm font-medium">Add bar</button>
      </form>
    </div>

    <!-- Plates -->
    <div>
      <h4 class="text-sm font-medium text-surface-200">Plates</h4>
      <p class="text-xs text-surface-500 mt-0.5">Denominations you own (each loaded as a pair, one per side).</p>
      <div class="flex flex-wrap gap-2 mt-3">
        {#each profile.plate_weights_kg as w (w)}
          <span class="inline-flex items-center gap-1.5 pl-3 pr-1.5 py-1 rounded-full bg-primary-500/15 text-primary-200 text-sm">
            {formatWeight(w)} kg
            <button onclick={() => removeWeight('plate_weights_kg', w)} class="w-5 h-5 rounded-full hover:bg-primary-500/30 text-primary-300/70 hover:text-primary-200 flex items-center justify-center" aria-label="Remove {w} kg plate">×</button>
          </span>
        {/each}
        {#if profile.plate_weights_kg.length === 0}
          <span class="text-xs text-surface-500">No plates — only the bare bar is loadable.</span>
        {/if}
      </div>
      <form class="flex gap-2 mt-3" onsubmit={(e) => { e.preventDefault(); addWeight('plate_weights_kg', newPlate); newPlate = ''; }}>
        <input type="number" inputmode="decimal" step="0.25" bind:value={newPlate} placeholder="e.g. 2.5" class="w-28 px-3 py-1.5 bg-surface-900 border border-surface-700 rounded-lg text-surface-100 text-sm focus:outline-none focus:border-primary-500" aria-label="New plate weight in kg" />
        <button type="submit" class="px-3 py-1.5 rounded-lg bg-surface-700 hover:bg-surface-600 text-surface-200 text-sm font-medium">Add plate</button>
      </form>
    </div>

    <!-- Plate calculator preview -->
    {#if preview}
      <div class="rounded-lg bg-surface-900/70 border border-surface-700 p-3">
        <div class="flex items-center justify-between gap-3">
          <label class="text-xs text-surface-400" for="preview-target">Plate calculator</label>
          <div class="flex items-center gap-1.5">
            <input id="preview-target" type="number" inputmode="decimal" step="2.5" bind:value={previewTarget} class="w-20 px-2 py-1 bg-surface-900 border border-surface-700 rounded-md text-surface-100 text-sm text-center focus:outline-none focus:border-primary-500" />
            <span class="text-xs text-surface-500">kg target</span>
          </div>
        </div>
        <p class="mt-2 text-sm text-surface-200">
          {#if preview.perSide.length > 0}
            Per side: {preview.perSide.map((p) => formatWeight(p)).join(' + ')} kg
          {:else}
            Bare bar
          {/if}
          <span class="text-surface-500"> · loads {formatWeight(preview.total)} kg</span>
          {#if !preview.exact}
            <span class="text-amber-400"> (closest to {formatWeight(previewTarget)} kg)</span>
          {/if}
        </p>
      </div>
    {/if}

    <!-- Equipment -->
    <div>
      <h4 class="text-sm font-medium text-surface-200">Equipment</h4>
      <p class="text-xs text-surface-500 mt-0.5">What's available — used to tailor workout recommendations.</p>
      <div class="flex flex-wrap gap-2 mt-3">
        {#each profile.equipment as e (e)}
          <span class="inline-flex items-center gap-1.5 pl-3 pr-1.5 py-1 rounded-full bg-surface-700 text-surface-200 text-sm capitalize">
            {e}
            <button onclick={() => removeEquipment(e)} class="w-5 h-5 rounded-full hover:bg-surface-600 text-surface-400 hover:text-surface-200 flex items-center justify-center" aria-label="Remove {e}">×</button>
          </span>
        {/each}
      </div>
      <div class="flex flex-wrap gap-1.5 mt-3">
        {#each EQUIPMENT_SUGGESTIONS.filter((s) => !profile!.equipment.some((e) => e.toLowerCase() === s)) as s}
          <button onclick={() => addEquipment(s)} class="px-2.5 py-1 rounded-full border border-dashed border-surface-600 text-surface-400 hover:text-primary-300 hover:border-primary-500/50 text-xs capitalize transition-colors">+ {s}</button>
        {/each}
      </div>
      <form class="flex gap-2 mt-3" onsubmit={(e) => { e.preventDefault(); addEquipment(newEquipment); newEquipment = ''; }}>
        <input type="text" bind:value={newEquipment} placeholder="Other equipment" class="flex-1 px-3 py-1.5 bg-surface-900 border border-surface-700 rounded-lg text-surface-100 text-sm focus:outline-none focus:border-primary-500" aria-label="New equipment" />
        <button type="submit" class="px-3 py-1.5 rounded-lg bg-surface-700 hover:bg-surface-600 text-surface-200 text-sm font-medium">Add</button>
      </form>
    </div>

    {#if error}
      <p class="text-sm text-red-400">{error}</p>
    {/if}

    <div class="flex items-center gap-3 pt-1">
      <button onclick={save} disabled={saving} class="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white font-semibold text-sm transition-colors disabled:opacity-50">
        {saving ? 'Saving…' : 'Save'}
      </button>
      {#if savedFlash}
        <span class="text-sm text-primary-400">Saved</span>
      {/if}
    </div>
  {/if}
</div>
