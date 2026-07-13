<script lang="ts">
  import { api } from '$lib/api';
  import type { Exclusion } from '$lib/types';

  // The Exclusions manager (CONTEXT.md "Exclusion"): every "don't suggest this
  // again" set from a SwapSheet lands here, reviewable and reversible — the
  // engine never keeps an invisible blocklist.
  let exclusions = $state<Exclusion[] | null>(null);
  let error = $state('');
  let removing = $state<string | null>(null);

  $effect(() => {
    void load();
  });

  async function load() {
    error = '';
    try {
      exclusions = await api.get<Exclusion[]>('/api/exercises/exclusions');
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to load exclusions';
      exclusions = exclusions ?? [];
    }
  }

  async function remove(exerciseId: string) {
    removing = exerciseId;
    error = '';
    try {
      await api.delete(`/api/exercises/${exerciseId}/exclusion`);
      exclusions = (exclusions ?? []).filter((e) => e.exercise_id !== exerciseId);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to remove the exclusion';
    } finally {
      removing = null;
    }
  }
</script>

{#if error}
  <p class="text-sm text-red-400 mb-2">{error}</p>
{/if}

{#if exclusions === null}
  <div class="h-12 bg-surface-800 rounded-lg animate-pulse"></div>
{:else if exclusions.length === 0}
  <p class="text-sm text-surface-500">
    None yet. When swapping an exercise mid-workout you can mark it “don't
    suggest again” — it shows up here, and recommendations skip it until you
    remove the mark.
  </p>
{:else}
  <ul class="space-y-1.5">
    {#each exclusions as ex (ex.exercise_id)}
      <li
        class="flex items-center justify-between gap-3 p-3 rounded-lg bg-surface-800 border border-surface-700"
      >
        <div class="min-w-0">
          <p class="text-sm font-medium text-surface-200 truncate">{ex.name}</p>
          {#if ex.equipment}
            <p class="text-xs text-surface-500 truncate">{ex.equipment}</p>
          {/if}
        </div>
        <button
          onclick={() => remove(ex.exercise_id)}
          disabled={removing === ex.exercise_id}
          class="shrink-0 px-2.5 py-1.5 rounded-lg text-xs font-medium text-surface-300 bg-surface-700 hover:bg-surface-600 transition-colors disabled:opacity-50"
        >
          {removing === ex.exercise_id ? 'Removing…' : 'Allow again'}
        </button>
      </li>
    {/each}
  </ul>
{/if}
