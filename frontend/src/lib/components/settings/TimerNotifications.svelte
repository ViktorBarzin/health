<script lang="ts">
  import { PUSH_ENABLED_KV, type PushStatus } from '$lib/push';
  import { disablePush, enablePush, getPushStatus } from '$lib/push-client';
  import { putKV } from '$lib/sync/store';

  // Rest-timer notifications (ADR-0010): the locked-phone cue that also lands
  // on a paired Apple Watch via iOS lock-screen mirroring. The permission
  // prompt MUST come from this tap (iOS requires a user gesture, and only for
  // an installed PWA), so the whole enable flow hangs off the button.
  let status = $state<PushStatus | 'loading'>('loading');
  let busy = $state(false);
  let error = $state('');

  $effect(() => {
    void getPushStatus().then((s) => (status = s));
  });

  async function toggle() {
    if (busy) return;
    busy = true;
    error = '';
    try {
      if (status === 'on') {
        status = await disablePush();
        await putKV(PUSH_ENABLED_KV, false);
      } else {
        status = await enablePush();
        await putKV(PUSH_ENABLED_KV, status === 'on');
        if (status === 'denied') {
          error =
            'Notifications are blocked for this app in the system settings — allow them there, then try again.';
        }
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'Failed to update notifications';
    } finally {
      busy = false;
    }
  }
</script>

{#if status === 'loading'}
  <div class="h-12 bg-surface-800 rounded-lg animate-pulse"></div>
{:else if status === 'unsupported'}
  <p class="text-sm text-surface-500">
    This browser can't show push notifications. On iPhone, install the app first
    (Share → Add to Home Screen) and open it from the Home Screen — then the
    toggle appears here.
  </p>
{:else if status === 'unconfigured'}
  <p class="text-sm text-surface-500">
    Push isn't configured on the server yet (VAPID keys not deployed).
  </p>
{:else}
  <div class="flex items-center justify-between gap-3 p-3 rounded-lg bg-surface-800 border border-surface-700">
    <div class="min-w-0">
      <p class="text-sm font-medium text-surface-200">Rest-timer notifications</p>
      <p class="text-xs text-surface-500">
        When the phone is locked, the "rest over" cue arrives as a notification —
        it buzzes a paired watch too.
      </p>
    </div>
    <button
      onclick={toggle}
      disabled={busy || status === 'denied'}
      class="shrink-0 px-3 py-2 rounded-lg text-xs font-semibold transition-colors disabled:opacity-50
             {status === 'on'
        ? 'bg-primary-500/20 text-primary-300 hover:bg-primary-500/30'
        : 'bg-surface-700 text-surface-200 hover:bg-surface-600'}"
    >
      {busy ? '…' : status === 'on' ? 'On — turn off' : 'Turn on'}
    </button>
  </div>
  {#if status === 'denied'}
    <p class="mt-2 text-xs text-amber-400">
      Notifications are blocked at the OS level for this app — allow them in the
      system settings, then come back.
    </p>
  {/if}
{/if}

{#if error}
  <p class="mt-2 text-sm text-red-400">{error}</p>
{/if}
