<script lang="ts">
  import { api } from '$lib/api';
  import { looksLikeFitbodCsv } from '$lib/fitbod';
  import type {
    ExerciseSummary,
    FitbodImportResult,
    FitbodPreview,
    FitbodUnresolvedName,
  } from '$lib/types';
  import ExercisePicker from '$lib/components/sessions/ExercisePicker.svelte';

  // The "Import from Fitbod" flow (#9): upload CSV → preview/summary → resolve
  // any unmatched exercise names → confirm → imported. Mobile-friendly; the
  // manual matcher reuses the library ExercisePicker bottom-sheet.
  type Step = 'upload' | 'preview' | 'done';

  let step = $state<Step>('upload');
  let busy = $state(false);
  let error = $state('');

  // Held across steps: the CSV text (re-sent on commit — the server is
  // stateless and the import is idempotent) and the dry-run preview.
  let csvText = $state('');
  let filename = $state('fitbod.csv');
  let preview = $state<FitbodPreview | null>(null);
  let result = $state<FitbodImportResult | null>(null);

  // User's manual resolutions: Fitbod name → chosen Exercise {id, name}.
  let resolutions = $state<Record<string, { id: string; name: string }>>({});

  // The ExercisePicker target: which unresolved name we're resolving now.
  let pickerOpen = $state(false);
  let pickingName = $state<string | null>(null);

  let unresolvedRemaining = $derived(
    (preview?.unresolved ?? []).filter((u) => !resolutions[u.fitbod_name]),
  );

  async function handleFile(file: File) {
    error = '';
    const text = await file.text();
    if (!looksLikeFitbodCsv(text)) {
      error =
        "This doesn't look like a Fitbod export. In Fitbod, go to Settings → Export Workout Data and upload that CSV.";
      return;
    }
    csvText = text;
    filename = file.name || 'fitbod.csv';
    await runPreview();
  }

  async function onFileInput(e: Event) {
    const input = e.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      await handleFile(input.files[0]);
    }
  }

  async function runPreview() {
    busy = true;
    error = '';
    try {
      preview = await api.post<FitbodPreview>('/api/import/fitbod/preview', {
        csv_text: csvText,
      });
      resolutions = {};
      step = 'preview';
    } catch (err) {
      error = err instanceof Error ? err.message : 'Could not read that CSV.';
    } finally {
      busy = false;
    }
  }

  function openPickerFor(name: string) {
    pickingName = name;
    pickerOpen = true;
  }

  function onExercisePicked(ex: ExerciseSummary) {
    if (pickingName) {
      resolutions = {
        ...resolutions,
        [pickingName]: { id: ex.id, name: ex.name },
      };
    }
    pickerOpen = false;
    pickingName = null;
  }

  function clearResolution(name: string) {
    const next = { ...resolutions };
    delete next[name];
    resolutions = next;
  }

  async function confirmImport() {
    if (busy || preview === null) return;
    busy = true;
    error = '';
    try {
      const resolutionMap: Record<string, string> = {};
      for (const [name, ex] of Object.entries(resolutions)) {
        resolutionMap[name] = ex.id;
      }
      result = await api.post<FitbodImportResult>('/api/import/fitbod/commit', {
        csv_text: csvText,
        filename,
        resolutions: resolutionMap,
      });
      step = 'done';
    } catch (err) {
      error = err instanceof Error ? err.message : 'Import failed. Please try again.';
    } finally {
      busy = false;
    }
  }

  function reset() {
    step = 'upload';
    csvText = '';
    preview = null;
    result = null;
    resolutions = {};
    error = '';
  }
</script>

<div class="bg-surface-800 rounded-xl border border-surface-700 p-6 space-y-5">
  {#if step === 'upload'}
    <!-- Step 1: upload -->
    <label
      class="block border-2 border-dashed rounded-xl p-8 text-center transition-colors
             border-surface-600 hover:border-surface-500
             {busy ? 'pointer-events-none opacity-60' : 'cursor-pointer'}"
    >
      {#if busy}
        <div class="flex flex-col items-center gap-3">
          <div class="w-8 h-8 border-3 border-primary-500 border-t-transparent rounded-full animate-spin"></div>
          <p class="text-sm text-surface-300">Reading your workout history…</p>
        </div>
      {:else}
        <div class="flex flex-col items-center gap-3">
          <svg class="w-10 h-10 text-surface-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
          </svg>
          <div>
            <p class="text-sm text-surface-200 font-medium">Upload your Fitbod CSV</p>
            <p class="text-xs text-surface-500 mt-1">Fitbod → Settings → Export Workout Data</p>
          </div>
          <span class="mt-2 px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium rounded-lg">
            Choose file
          </span>
        </div>
      {/if}
      <input type="file" accept=".csv,text/csv" class="hidden" onchange={onFileInput} disabled={busy} />
    </label>
  {/if}

  {#if step === 'preview' && preview}
    <!-- Step 2: preview + resolve -->
    <div>
      <h4 class="text-sm font-semibold text-surface-100">Ready to import</h4>
      <p class="text-sm text-surface-400 mt-1">
        {preview.session_count} session{preview.session_count === 1 ? '' : 's'},
        {preview.set_count} set{preview.set_count === 1 ? '' : 's'}
        {#if preview.skipped_rows > 0}
          · {preview.skipped_rows} non-strength row{preview.skipped_rows === 1 ? '' : 's'} skipped
        {/if}
      </p>
    </div>

    {#if preview.unresolved.length > 0}
      <div class="space-y-3">
        <div>
          <p class="text-sm font-medium text-surface-200">
            Match {preview.unresolved.length} exercise{preview.unresolved.length === 1 ? '' : 's'}
          </p>
          <p class="text-xs text-surface-500 mt-0.5">
            We couldn't match these Fitbod names automatically. Pick the matching exercise (or
            <a href="/exercises/new" class="text-primary-400 hover:underline">create a custom one</a>)
            for each.
          </p>
        </div>
        <ul class="space-y-2">
          {#each preview.unresolved as u (u.fitbod_name)}
            {@const chosen = resolutions[u.fitbod_name]}
            <li class="flex items-center justify-between gap-3 bg-surface-900 border border-surface-700 rounded-lg p-3">
              <div class="min-w-0">
                <p class="text-sm font-medium text-surface-200 truncate">{u.fitbod_name}</p>
                <p class="text-xs text-surface-500">{u.set_count} set{u.set_count === 1 ? '' : 's'}</p>
              </div>
              {#if chosen}
                <div class="flex items-center gap-2 shrink-0">
                  <span class="text-xs text-emerald-400 font-medium truncate max-w-[8rem]" title={chosen.name}>
                    → {chosen.name}
                  </span>
                  <button
                    onclick={() => clearResolution(u.fitbod_name)}
                    class="text-xs text-surface-400 hover:text-surface-200 underline"
                  >
                    change
                  </button>
                </div>
              {:else}
                <button
                  onclick={() => openPickerFor(u.fitbod_name)}
                  class="shrink-0 px-3 py-1.5 text-xs font-medium rounded-lg bg-surface-700 hover:bg-surface-600 text-surface-100"
                >
                  Match…
                </button>
              {/if}
            </li>
          {/each}
        </ul>
        {#if unresolvedRemaining.length > 0}
          <p class="text-xs text-amber-400">
            {unresolvedRemaining.length} still to match. Unmatched names will be skipped if you import now.
          </p>
        {/if}
      </div>
    {:else}
      <p class="text-sm text-emerald-400">All exercises matched to your library.</p>
    {/if}

    <div class="flex items-center gap-3 pt-1">
      {#if unresolvedRemaining.length > 0}
        <!-- Names still unmatched: the only action that imports also skips them. -->
        <button
          onclick={confirmImport}
          disabled={busy}
          class="px-4 py-2 bg-primary-500 hover:bg-primary-600 disabled:opacity-50 text-white text-sm font-medium rounded-lg"
        >
          {busy ? 'Importing…' : 'Skip unmatched & import'}
        </button>
      {:else}
        <button
          onclick={confirmImport}
          disabled={busy}
          class="px-4 py-2 bg-primary-500 hover:bg-primary-600 disabled:opacity-50 text-white text-sm font-medium rounded-lg"
        >
          {busy ? 'Importing…' : 'Import'}
        </button>
      {/if}
      <button onclick={reset} class="px-4 py-2 text-sm text-surface-400 hover:text-surface-200">
        Cancel
      </button>
    </div>
  {/if}

  {#if step === 'done' && result}
    <!-- Step 3: done -->
    <div class="text-center py-4 space-y-3">
      <div class="w-12 h-12 mx-auto rounded-full bg-emerald-500/15 flex items-center justify-center">
        <svg class="w-6 h-6 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
        </svg>
      </div>
      <div>
        <p class="text-sm font-semibold text-surface-100">Import complete</p>
        <p class="text-sm text-surface-400 mt-1">
          Added {result.sessions_created} session{result.sessions_created === 1 ? '' : 's'} and
          {result.sets_created} set{result.sets_created === 1 ? '' : 's'}.
          {#if result.unresolved_skipped > 0}
            {result.unresolved_skipped} unmatched set{result.unresolved_skipped === 1 ? '' : 's'} skipped.
          {/if}
        </p>
      </div>
      <div class="flex items-center justify-center gap-3">
        <a href="/sessions" class="px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium rounded-lg">
          View sessions
        </a>
        <button onclick={reset} class="px-4 py-2 text-sm text-surface-400 hover:text-surface-200">
          Import another
        </button>
      </div>
    </div>
  {/if}

  {#if error}
    <div class="p-3 rounded-lg bg-red-500/10 border border-red-500/20">
      <p class="text-sm text-red-400">{error}</p>
    </div>
  {/if}
</div>

<ExercisePicker open={pickerOpen} onpick={onExercisePicked} onclose={() => (pickerOpen = false)} />
