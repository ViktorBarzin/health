<script lang="ts">
  import { api } from '$lib/api';
  import { auth } from '$lib/stores/auth.svelte';
  import type { ImportStatus as ImportStatusType } from '$lib/types';
  import { formatDate } from '$lib/utils/format';
  import XmlUpload from '$lib/components/import/XmlUpload.svelte';
  import ImportStatusComponent from '$lib/components/import/ImportStatus.svelte';
  import FitbodImport from '$lib/components/import/FitbodImport.svelte';
  import GymProfileSettings from '$lib/components/settings/GymProfileSettings.svelte';

  let imports = $state<ImportStatusType[]>([]);
  let activeBatchId = $state<string | undefined>(undefined);
  let loadingImports = $state(true);

  $effect(() => {
    loadImports();
  });

  async function loadImports() {
    loadingImports = true;
    try {
      imports = await api.get<ImportStatusType[]>('/api/import/uploads');
    } catch {
      // May not have any imports yet
      imports = [];
    } finally {
      loadingImports = false;
    }
  }

  function handleUploadComplete(batchId: string) {
    activeBatchId = batchId;
  }
</script>

<div class="max-w-3xl mx-auto space-y-8">
  <!-- Gym Profile Section -->
  <section>
    <div class="mb-4">
      <h2 class="text-lg font-semibold text-surface-100">Gym Profile</h2>
      <p class="text-sm text-surface-500 mt-1">Your bars, plates, and equipment — powers the plate calculator and workout recommendations.</p>
    </div>
    <GymProfileSettings />
  </section>

  <!-- Data Import Section -->
  <section>
    <div class="mb-4">
      <h2 class="text-lg font-semibold text-surface-100">Data Import</h2>
      <p class="text-sm text-surface-500 mt-1">Upload your Apple Health export to import health data.</p>
    </div>

    <div class="bg-surface-800 rounded-xl border border-surface-700 p-6 space-y-6">
      <!-- Upload area -->
      <XmlUpload onUploadComplete={handleUploadComplete} />

      <!-- Active import status -->
      {#if activeBatchId}
        <div>
          <h4 class="text-sm font-medium text-surface-300 mb-3">Current Import</h4>
          <ImportStatusComponent batchId={activeBatchId} onRefresh={loadImports} />
        </div>
      {/if}

      <!-- Past imports -->
      {#if loadingImports}
        <div class="space-y-2">
          {#each Array(3) as _}
            <div class="bg-surface-700/50 rounded-lg p-3 animate-pulse">
              <div class="flex items-center justify-between">
                <div class="space-y-1">
                  <div class="w-32 h-4 bg-surface-600 rounded"></div>
                  <div class="w-20 h-3 bg-surface-600 rounded"></div>
                </div>
                <div class="w-16 h-4 bg-surface-600 rounded"></div>
              </div>
            </div>
          {/each}
        </div>
      {:else if imports.length > 0}
        <ImportStatusComponent imports={imports} onDelete={loadImports} />
      {:else}
        <div class="text-center py-4">
          <p class="text-sm text-surface-500">No previous imports found.</p>
        </div>
      {/if}
    </div>
  </section>

  <!-- Fitbod Import Section -->
  <section>
    <div class="mb-4">
      <h2 class="text-lg font-semibold text-surface-100">Import from Fitbod</h2>
      <p class="text-sm text-surface-500 mt-1">Bring your Fitbod workout history in as Sessions — it seeds your strength records and progression.</p>
    </div>
    <FitbodImport />
  </section>

  <!-- Account Section -->
  <section>
    <div class="mb-4">
      <h2 class="text-lg font-semibold text-surface-100">Account</h2>
      <p class="text-sm text-surface-500 mt-1">Manage your account settings.</p>
    </div>

    <div class="bg-surface-800 rounded-xl border border-surface-700 divide-y divide-surface-700">
      <!-- Email -->
      <div class="flex items-center justify-between px-6 py-4">
        <div>
          <p class="text-sm text-surface-400">Email</p>
          <p class="text-sm font-medium text-surface-200 mt-0.5">{auth.user?.email ?? '--'}</p>
        </div>
      </div>

      <!-- Account created -->
      <div class="flex items-center justify-between px-6 py-4">
        <div>
          <p class="text-sm text-surface-400">Account Created</p>
          <p class="text-sm font-medium text-surface-200 mt-0.5">
            {auth.user?.created_at ? formatDate(auth.user.created_at, 'long') : '--'}
          </p>
        </div>
      </div>
    </div>
  </section>

  <!-- App Info -->
  <section>
    <div class="mb-4">
      <h2 class="text-lg font-semibold text-surface-100">About</h2>
    </div>

    <div class="bg-surface-800 rounded-xl border border-surface-700 divide-y divide-surface-700">
      <div class="flex items-center justify-between px-6 py-4">
        <p class="text-sm text-surface-400">Version</p>
        <p class="text-sm text-surface-200">1.0.0</p>
      </div>
      <div class="flex items-center justify-between px-6 py-4">
        <p class="text-sm text-surface-400">Data Source</p>
        <p class="text-sm text-surface-200">Apple Health Export</p>
      </div>
    </div>
  </section>
</div>
