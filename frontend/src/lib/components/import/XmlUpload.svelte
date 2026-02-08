<script lang="ts">
  import { api } from '$lib/api';

  interface Props {
    onUploadComplete?: (batchId: string) => void;
  }

  let { onUploadComplete }: Props = $props();

  let dragging = $state(false);
  let uploading = $state(false);
  let error = $state('');
  let progress = $state('');

  function handleDragOver(e: DragEvent) {
    e.preventDefault();
    dragging = true;
  }

  function handleDragLeave() {
    dragging = false;
  }

  async function handleDrop(e: DragEvent) {
    e.preventDefault();
    dragging = false;
    const files = e.dataTransfer?.files;
    if (files && files.length > 0) {
      await uploadFile(files[0]);
    }
  }

  async function handleFileSelect(e: Event) {
    const input = e.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      await uploadFile(input.files[0]);
    }
  }

  async function uploadFile(file: File) {
    if (!file.name.endsWith('.xml') && !file.name.endsWith('.zip')) {
      error = 'Please upload an XML or ZIP file exported from Apple Health.';
      return;
    }

    error = '';
    uploading = true;
    progress = `Uploading ${file.name}...`;

    try {
      const formData = new FormData();
      formData.append('file', file);

      const result = await api.upload<{ batch_id: string }>('/api/import/upload', formData);
      progress = 'Upload complete! Processing...';
      onUploadComplete?.(result.batch_id);
    } catch (err) {
      if (err instanceof Error) {
        error = err.message;
      } else {
        error = 'Upload failed. Please try again.';
      }
    } finally {
      uploading = false;
    }
  }
</script>

<div
  class="border-2 border-dashed rounded-xl p-8 text-center transition-colors
         {dragging ? 'border-primary-400 bg-primary-500/10' : 'border-surface-600 hover:border-surface-500'}
         {uploading ? 'pointer-events-none opacity-60' : 'cursor-pointer'}"
  ondragover={handleDragOver}
  ondragleave={handleDragLeave}
  ondrop={handleDrop}
  role="button"
  tabindex="0"
>
  {#if uploading}
    <div class="flex flex-col items-center gap-3">
      <div class="w-8 h-8 border-3 border-primary-500 border-t-transparent rounded-full animate-spin"></div>
      <p class="text-sm text-surface-300">{progress}</p>
    </div>
  {:else}
    <div class="flex flex-col items-center gap-3">
      <svg class="w-10 h-10 text-surface-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
      </svg>
      <div>
        <p class="text-sm text-surface-200 font-medium">
          Drag and drop your Apple Health export
        </p>
        <p class="text-xs text-surface-500 mt-1">
          XML or ZIP file from Apple Health app
        </p>
      </div>
      <label
        class="mt-2 px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium rounded-lg cursor-pointer transition-colors"
      >
        Browse Files
        <input type="file" accept=".xml,.zip" class="hidden" onchange={handleFileSelect} />
      </label>
    </div>
  {/if}

  {#if error}
    <div class="mt-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20">
      <p class="text-sm text-red-400">{error}</p>
    </div>
  {/if}
</div>
