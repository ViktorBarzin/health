<script lang="ts">
  import { api } from '$lib/api';
  import type { ImportStatus } from '$lib/types';
  import { formatDate } from '$lib/utils/format';

  interface Props {
    batchId?: string;
    imports?: ImportStatus[];
  }

  let { batchId, imports = [] }: Props = $props();

  let currentStatus = $state<ImportStatus | null>(null);
  let polling = $state(false);
  let pollTimer: ReturnType<typeof setInterval> | null = null;

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
      if (currentStatus.status === 'completed' || currentStatus.status === 'failed') {
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

  function statusColor(status: string): string {
    switch (status) {
      case 'completed': return 'text-green-400';
      case 'processing': return 'text-yellow-400';
      case 'failed': return 'text-red-400';
      case 'pending': return 'text-surface-400';
      default: return 'text-surface-400';
    }
  }

  function statusBg(status: string): string {
    switch (status) {
      case 'completed': return 'bg-green-500/10 border-green-500/20';
      case 'processing': return 'bg-yellow-500/10 border-yellow-500/20';
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
        {:else if currentStatus.status === 'completed'}
          <svg class="w-5 h-5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        {:else if currentStatus.status === 'failed'}
          <svg class="w-5 h-5 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
          </svg>
        {/if}
        <div>
          <p class="text-sm font-medium text-surface-200">{currentStatus.filename}</p>
          <p class="text-xs {statusColor(currentStatus.status)} capitalize">{currentStatus.status}</p>
        </div>
      </div>
      <div class="text-right">
        <p class="text-sm font-medium text-surface-200">{currentStatus.record_count.toLocaleString()} records</p>
      </div>
    </div>
  </div>
{/if}

{#if imports.length > 0}
  <div class="mt-4 space-y-2">
    <h4 class="text-sm font-medium text-surface-400">Import History</h4>
    {#each imports as imp}
      <div class="flex items-center justify-between p-3 rounded-lg bg-surface-800/50 border border-surface-700">
        <div class="flex items-center gap-3">
          <div class="w-2 h-2 rounded-full {imp.status === 'completed' ? 'bg-green-400' : imp.status === 'failed' ? 'bg-red-400' : 'bg-yellow-400'}"></div>
          <div>
            <p class="text-sm text-surface-200">{imp.filename}</p>
            <p class="text-xs text-surface-500">{formatDate(imp.imported_at)}</p>
          </div>
        </div>
        <div class="text-right">
          <p class="text-sm text-surface-300">{imp.record_count.toLocaleString()} records</p>
          <p class="text-xs {statusColor(imp.status)} capitalize">{imp.status}</p>
        </div>
      </div>
    {/each}
  </div>
{/if}
