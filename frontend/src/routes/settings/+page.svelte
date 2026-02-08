<script lang="ts">
  import { api } from '$lib/api';
  import { auth } from '$lib/stores/auth.svelte';
  import { goto } from '$app/navigation';
  import type { ImportStatus as ImportStatusType } from '$lib/types';
  import { formatDate } from '$lib/utils/format';
  import XmlUpload from '$lib/components/import/XmlUpload.svelte';
  import ImportStatusComponent from '$lib/components/import/ImportStatus.svelte';

  let imports = $state<ImportStatusType[]>([]);
  let activeBatchId = $state<string | undefined>(undefined);
  let loadingImports = $state(true);
  let loggingOut = $state(false);

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
    // Refresh the imports list after a delay
    setTimeout(() => {
      loadImports();
    }, 5000);
  }

  async function handleLogout() {
    loggingOut = true;
    await auth.logout();
    goto('/login');
  }
</script>

<div class="max-w-3xl mx-auto space-y-8">
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
          <ImportStatusComponent batchId={activeBatchId} />
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
        <ImportStatusComponent imports={imports} />
      {:else}
        <div class="text-center py-4">
          <p class="text-sm text-surface-500">No previous imports found.</p>
        </div>
      {/if}
    </div>
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

      <!-- Logout -->
      <div class="px-6 py-4">
        <button
          onclick={handleLogout}
          disabled={loggingOut}
          class="px-4 py-2 bg-red-500/10 hover:bg-red-500/20 border border-red-500/20 hover:border-red-500/30
                 text-red-400 text-sm font-medium rounded-lg transition-colors
                 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {#if loggingOut}
            <span class="flex items-center gap-2">
              <div class="w-4 h-4 border-2 border-red-400 border-t-transparent rounded-full animate-spin"></div>
              Signing out...
            </span>
          {:else}
            Sign Out
          {/if}
        </button>
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
