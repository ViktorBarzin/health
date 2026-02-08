<script lang="ts">
  import { api } from '$lib/api';
  import type { ImportStatus } from '$lib/types';
  import { formatDate } from '$lib/utils/format';

  interface Props {
    batchId?: string;
    imports?: ImportStatus[];
    onDelete?: () => void;
    onRefresh?: () => void;
  }

  let { batchId, imports = [], onDelete, onRefresh }: Props = $props();

  let currentStatus = $state<ImportStatus | null>(null);
  let polling = $state(false);
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  let deletingBatchId = $state<string | null>(null);
  let confirmDeleteId = $state<string | null>(null);
  let deleteError = $state<string | null>(null);
  let cancellingBatchId = $state<string | null>(null);

  $effect(() => {
    if (batchId) {
      polling = true;
      pollStatus(batchId);

      pollTimer = setInterval(() => {
        pollStatus(batchId!);
      }, 3000);
    }

    return () => {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };
  });

  async function pollStatus(id: string) {
    try {
      currentStatus = await api.get<ImportStatus>(`/api/import/upload/status/${id}`);
      onRefresh?.();
      if (currentStatus.status === 'completed' || currentStatus.status === 'failed' || currentStatus.status === 'cancelled') {
        polling = false;
        if (pollTimer) {
          clearInterval(pollTimer);
          pollTimer = null;
        }
      }
    } catch {
      // Ignore polling errors
    }
  }

  async function handleDelete(batchId: string) {
    deletingBatchId = batchId;
    deleteError = null;
    try {
      await api.delete(`/api/import/upload/${batchId}`);
      confirmDeleteId = null;
      onDelete?.();
    } catch (e) {
      deleteError = e instanceof Error ? e.message : 'Failed to delete import';
    } finally {
      deletingBatchId = null;
    }
  }

  async function handleCancel(id: string) {
    cancellingBatchId = id;
    try {
      await api.post(`/api/import/upload/${id}/cancel`, {});
    } catch (e) {
      deleteError = e instanceof Error ? e.message : 'Failed to cancel import';
    } finally {
      cancellingBatchId = null;
    }
  }

  function statusColor(status: string): string {
    switch (status) {
      case 'completed': return 'text-green-400';
      case 'processing': return 'text-yellow-400';
      case 'cancelling': return 'text-orange-400';
      case 'cancelled': return 'text-orange-400';
      case 'failed': return 'text-red-400';
      case 'pending': return 'text-surface-400';
      default: return 'text-surface-400';
    }
  }

  function statusBg(status: string): string {
    switch (status) {
      case 'completed': return 'bg-green-500/10 border-green-500/20';
      case 'processing': return 'bg-yellow-500/10 border-yellow-500/20';
      case 'cancelling': return 'bg-orange-500/10 border-orange-500/20';
      case 'cancelled': return 'bg-orange-500/10 border-orange-500/20';
      case 'failed': return 'bg-red-500/10 border-red-500/20';
      default: return 'bg-surface-700/50 border-surface-600';
    }
  }
</script>

{#if currentStatus}
  <div class="p-4 rounded-lg border {statusBg(currentStatus.status)}">
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        {#if currentStatus.status === 'processing'}
          <div class="w-4 h-4 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin"></div>
        {:else if currentStatus.status === 'cancelling'}
          <div class="w-4 h-4 border-2 border-orange-400 border-t-transparent rounded-full animate-spin"></div>
        {:else if currentStatus.status === 'completed'}
          <svg class="w-5 h-5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        {:else if currentStatus.status === 'failed'}
          <svg class="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
        {:else if currentStatus.status === 'cancelled'}
          <svg class="w-5 h-5 text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636" />
          </svg>
        {/if}
        <div>
          <p class="text-sm font-medium text-surface-200">{currentStatus.filename}</p>
          <p class="text-xs {statusColor(currentStatus.status)} capitalize">{currentStatus.status}</p>
        </div>
      </div>
      <div class="flex items-center gap-3">
        <div class="text-right">
          <p class="text-sm font-medium text-surface-200">
            {currentStatus.record_count.toLocaleString()} records{#if currentStatus.status === 'processing' || currentStatus.status === 'cancelling'} processed{/if}
          </p>
        </div>
        {#if currentStatus.status === 'processing'}
          <button
            onclick={() => handleCancel(currentStatus!.batch_id)}
            disabled={cancellingBatchId === currentStatus.batch_id}
            class="px-2 py-1 text-xs bg-orange-500/20 hover:bg-orange-500/30 border border-orange-500/30
                   text-orange-400 rounded transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
        {:else if currentStatus.status === 'cancelling'}
          <span class="text-xs text-orange-400">Cancelling...</span>
        {/if}
      </div>
    </div>
  </div>
{/if}

{#if imports.length > 0}
  <div class="mt-4 space-y-2">
    <h4 class="text-sm font-medium text-surface-400">Import History</h4>
    {#if deleteError}
      <div class="p-2 rounded border border-red-500/20 bg-red-500/10 text-red-400 text-xs">
        {deleteError}
      </div>
    {/if}
    {#each imports as imp}
      <div class="flex items-center justify-between p-3 rounded-lg bg-surface-800/50 border border-surface-700">
        <div class="flex items-center gap-3">
          <div class="w-2 h-2 rounded-full {imp.status === 'completed' ? 'bg-green-400' : imp.status === 'failed' ? 'bg-red-400' : imp.status === 'cancelled' || imp.status === 'cancelling' ? 'bg-orange-400' : 'bg-yellow-400'}"></div>
          <div>
            <p class="text-sm text-surface-200">{imp.filename}</p>
            <p class="text-xs text-surface-500">{formatDate(imp.imported_at)}</p>
          </div>
        </div>
        <div class="flex items-center gap-3">
          <div class="text-right">
            <p class="text-sm text-surface-300">{imp.record_count.toLocaleString()} records</p>
            <p class="text-xs {statusColor(imp.status)} capitalize">{imp.status}</p>
          </div>
          {#if imp.status !== 'processing' && imp.status !== 'cancelling'}
            {#if confirmDeleteId === imp.batch_id}
              <div class="flex items-center gap-1">
                <button
                  onclick={() => handleDelete(imp.batch_id)}
                  disabled={deletingBatchId === imp.batch_id}
                  class="px-2 py-1 text-xs bg-red-500/20 hover:bg-red-500/30 border border-red-500/30
                         text-red-400 rounded transition-colors disabled:opacity-50"
                >
                  {#if deletingBatchId === imp.batch_id}
                    <div class="w-3 h-3 border-2 border-red-400 border-t-transparent rounded-full animate-spin"></div>
                  {:else}
                    Confirm
                  {/if}
                </button>
                <button
                  onclick={() => confirmDeleteId = null}
                  class="px-2 py-1 text-xs bg-surface-700 hover:bg-surface-600 border border-surface-600
                         text-surface-300 rounded transition-colors"
                >
                  Cancel
                </button>
              </div>
            {:else}
              <button
                onclick={() => confirmDeleteId = imp.batch_id}
                class="p-1.5 text-surface-500 hover:text-red-400 hover:bg-red-500/10
                       rounded transition-colors"
                title="Delete this import"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
                </svg>
              </button>
            {/if}
          {/if}
        </div>
      </div>
    {/each}
  </div>
{/if}
