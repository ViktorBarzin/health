<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import type { ExerciseDetail, MuscleOption } from '$lib/types';

  // Create a custom (private) Exercise. Muscles are chosen from the same typed
  // dimension the seeded catalog uses, so analytics stay consistent.
  let muscles = $state<MuscleOption[]>([]);
  let name = $state('');
  let equipment = $state('');
  let level = $state('');
  let mechanic = $state('');
  let force = $state('');
  let category = $state('');
  let instructionsText = $state('');
  let primary = $state<string[]>([]);
  let secondary = $state<string[]>([]);

  let saving = $state(false);
  let error = $state('');

  $effect(() => {
    loadMuscles();
  });

  async function loadMuscles() {
    try {
      muscles = await api.get<MuscleOption[]>('/api/exercises/muscles');
    } catch {
      // Form still works; muscle pickers will just be empty.
    }
  }

  function togglePrimary(value: string) {
    primary = primary.includes(value)
      ? primary.filter((m) => m !== value)
      : [...primary, value];
    // A muscle can't be both primary and secondary.
    secondary = secondary.filter((m) => m !== value);
  }

  function toggleSecondary(value: string) {
    if (primary.includes(value)) return;
    secondary = secondary.includes(value)
      ? secondary.filter((m) => m !== value)
      : [...secondary, value];
  }

  let canSave = $derived(name.trim().length > 0 && !saving);

  async function save() {
    if (!canSave) return;
    saving = true;
    error = '';
    try {
      const instructions = instructionsText
        .split('\n')
        .map((s) => s.trim())
        .filter(Boolean);
      const created = await api.post<ExerciseDetail>('/api/exercises/', {
        name: name.trim(),
        equipment: equipment || null,
        level: level || null,
        mechanic: mechanic || null,
        force: force || null,
        category: category || null,
        instructions,
        primary_muscles: primary,
        secondary_muscles: secondary,
      });
      await goto(`/exercises/${created.id}`);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to create exercise';
      saving = false;
    }
  }
</script>

<div class="space-y-6 max-w-2xl mx-auto">
  <a href="/exercises" class="inline-flex items-center gap-1.5 text-sm text-surface-400 hover:text-surface-200 transition-colors">
    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
      <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 19.5L8.25 12l7.5-7.5" />
    </svg>
    Exercises
  </a>

  <h1 class="text-2xl font-semibold text-surface-100">New custom exercise</h1>

  <form
    class="space-y-5"
    onsubmit={(e) => {
      e.preventDefault();
      save();
    }}
  >
    <!-- Name -->
    <div>
      <label for="name" class="block text-sm font-medium text-surface-300 mb-1.5">Name <span class="text-red-400">*</span></label>
      <input
        id="name"
        type="text"
        bind:value={name}
        required
        maxlength="200"
        placeholder="e.g. Single-arm cable row"
        class="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-lg
               text-surface-100 placeholder-surface-500 text-sm
               focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 transition-colors"
      />
    </div>

    <!-- Attributes -->
    <div class="grid grid-cols-2 gap-3">
      <div>
        <label for="equipment" class="block text-sm font-medium text-surface-300 mb-1.5">Equipment</label>
        <input id="equipment" type="text" bind:value={equipment} placeholder="e.g. cable"
          class="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 placeholder-surface-500 text-sm focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 transition-colors" />
      </div>
      <div>
        <label for="category" class="block text-sm font-medium text-surface-300 mb-1.5">Category</label>
        <input id="category" type="text" bind:value={category} placeholder="e.g. strength"
          class="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-lg text-surface-100 placeholder-surface-500 text-sm focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 transition-colors" />
      </div>
      <div>
        <label for="mechanic" class="block text-sm font-medium text-surface-300 mb-1.5">Mechanic</label>
        <div class="relative">
          <select id="mechanic" bind:value={mechanic}
            class="w-full appearance-none px-3 pr-8 py-2.5 bg-surface-800 border border-surface-700 rounded-lg text-surface-200 text-sm focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 transition-colors cursor-pointer">
            <option value="">—</option>
            <option value="compound">Compound</option>
            <option value="isolation">Isolation</option>
          </select>
          <svg class="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" /></svg>
        </div>
      </div>
      <div>
        <label for="force" class="block text-sm font-medium text-surface-300 mb-1.5">Force</label>
        <div class="relative">
          <select id="force" bind:value={force}
            class="w-full appearance-none px-3 pr-8 py-2.5 bg-surface-800 border border-surface-700 rounded-lg text-surface-200 text-sm focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 transition-colors cursor-pointer">
            <option value="">—</option>
            <option value="push">Push</option>
            <option value="pull">Pull</option>
            <option value="static">Static</option>
          </select>
          <svg class="absolute right-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-surface-400 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5"><path stroke-linecap="round" stroke-linejoin="round" d="M19.5 8.25l-7.5 7.5-7.5-7.5" /></svg>
        </div>
      </div>
    </div>

    <!-- Primary muscles -->
    <div>
      <span class="block text-sm font-medium text-surface-300 mb-1.5">Primary muscles</span>
      <div class="flex flex-wrap gap-1.5">
        {#each muscles as m}
          <button
            type="button"
            onclick={() => togglePrimary(m.value)}
            class="text-xs px-2.5 py-1 rounded-md border transition-colors
                   {primary.includes(m.value)
                     ? 'bg-primary-500/20 border-primary-500/50 text-primary-300'
                     : 'bg-surface-800 border-surface-700 text-surface-400 hover:border-surface-500'}"
          >
            {m.label}
          </button>
        {/each}
      </div>
    </div>

    <!-- Secondary muscles -->
    <div>
      <span class="block text-sm font-medium text-surface-300 mb-1.5">Secondary muscles</span>
      <div class="flex flex-wrap gap-1.5">
        {#each muscles as m}
          <button
            type="button"
            onclick={() => toggleSecondary(m.value)}
            disabled={primary.includes(m.value)}
            class="text-xs px-2.5 py-1 rounded-md border transition-colors
                   disabled:opacity-30 disabled:cursor-not-allowed
                   {secondary.includes(m.value)
                     ? 'bg-surface-600 border-surface-500 text-surface-100'
                     : 'bg-surface-800 border-surface-700 text-surface-400 hover:border-surface-500'}"
          >
            {m.label}
          </button>
        {/each}
      </div>
    </div>

    <!-- Instructions -->
    <div>
      <label for="instructions" class="block text-sm font-medium text-surface-300 mb-1.5">
        Instructions <span class="text-surface-500 font-normal">(one step per line)</span>
      </label>
      <textarea
        id="instructions"
        bind:value={instructionsText}
        rows="5"
        placeholder={"Set up at the cable machine.\nPull toward your hip.\nControl the return."}
        class="w-full px-3 py-2.5 bg-surface-800 border border-surface-700 rounded-lg
               text-surface-100 placeholder-surface-500 text-sm leading-relaxed
               focus:outline-none focus:border-primary-500 focus:ring-1 focus:ring-primary-500 transition-colors resize-y"
      ></textarea>
    </div>

    {#if error}
      <p class="text-sm text-red-400">{error}</p>
    {/if}

    <div class="flex gap-3">
      <button
        type="submit"
        disabled={!canSave}
        class="flex-1 py-2.5 bg-primary-500 hover:bg-primary-600 text-white font-medium text-sm rounded-lg
               transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {#if saving}
          <span class="flex items-center justify-center gap-2">
            <div class="w-4 h-4 border-2 border-white/50 border-t-transparent rounded-full animate-spin"></div>
            Saving...
          </span>
        {:else}
          Create exercise
        {/if}
      </button>
      <a
        href="/exercises"
        class="px-5 py-2.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 text-surface-300 font-medium text-sm rounded-lg transition-colors flex items-center"
      >
        Cancel
      </a>
    </div>
  </form>
</div>
