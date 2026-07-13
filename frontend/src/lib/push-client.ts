// Web Push client glue (ADR-0010): subscribe/unsubscribe + rest-timer schedule.
//
// The rest timer runs IN THE PAGE (lib/rest-timer.ts); the server push exists
// only to punch through a locked phone — and, via iOS lock-screen mirroring, to
// reach a paired Apple Watch. Everything here is best-effort: a failed schedule
// call must never break logging (the in-page beep still covers a lit screen),
// so the scheduling helpers swallow errors by design. Pure decode/support
// logic lives in lib/push.ts (vitest); this module owns the IO.

import { api } from './api';
import { pushSupported, urlBase64ToUint8Array, type PushStatus } from './push';

interface PushConfigRead {
  enabled: boolean;
  public_key: string | null;
}

/** The current end-to-end status, for the settings toggle. */
export async function getPushStatus(): Promise<PushStatus> {
  if (!pushSupported()) return 'unsupported';
  let config: PushConfigRead;
  try {
    config = await api.get<PushConfigRead>('/api/push/config');
  } catch {
    return 'unconfigured';
  }
  if (!config.enabled || !config.public_key) return 'unconfigured';
  if (Notification.permission === 'denied') return 'denied';
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    return sub ? 'on' : 'off';
  } catch {
    return 'off';
  }
}

/**
 * Turn timer notifications on: permission prompt (must be called from a user
 * gesture — iOS enforces it, and only for an installed PWA), subscribe with
 * the server's VAPID key, register the subscription server-side.
 */
export async function enablePush(): Promise<PushStatus> {
  if (!pushSupported()) return 'unsupported';
  const config = await api.get<PushConfigRead>('/api/push/config');
  if (!config.enabled || !config.public_key) return 'unconfigured';

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return permission === 'denied' ? 'denied' : 'off';

  const reg = await navigator.serviceWorker.ready;
  const subscription =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(config.public_key)
        .buffer as ArrayBuffer,
    }));
  await api.post('/api/push/subscriptions', subscription.toJSON());
  return 'on';
}

/** Turn timer notifications off: drop the browser + server subscription. */
export async function disablePush(): Promise<PushStatus> {
  if (!pushSupported()) return 'unsupported';
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      const endpoint = sub.endpoint;
      await sub.unsubscribe();
      await api.delete('/api/push/subscriptions', {
        body: JSON.stringify({ endpoint }),
        headers: { 'Content-Type': 'application/json' },
      });
    }
  } catch {
    // Best-effort: a dangling server row is harmless (the push service will
    // report it gone on the next send and the server prunes it).
  }
  return 'off';
}

/**
 * Schedule the locked-phone cue for a running rest countdown (best-effort,
 * silent — offline just means no push, the accepted ADR-0010 degradation).
 */
export async function schedulePushTimer(
  sessionId: string,
  endsAtMs: number,
  label: string,
): Promise<void> {
  try {
    await api.post('/api/push/rest-timer', {
      fire_at: new Date(endsAtMs).toISOString(),
      label,
      session_id: sessionId,
    });
  } catch {
    // silent by design
  }
}

/** Cancel the pending cue (skip / early next set / completed on-screen). */
export async function cancelPushTimer(): Promise<void> {
  try {
    await api.delete('/api/push/rest-timer');
  } catch {
    // silent by design — an offline cancel means one stray (harmless) buzz
  }
}
