// Pure Web Push helpers (ADR-0010) — vitest-covered; no IO, no api import
// (the api-touching glue lives in lib/push-client.ts, per the repo's
// pure-lib / IO-glue split).

/** IndexedDB kv key for "the user turned timer notifications on here". */
export const PUSH_ENABLED_KV = 'push:enabled';

export type PushStatus =
  | 'unsupported' // browser has no push (or the PWA isn't installed on iOS)
  | 'unconfigured' // server has no VAPID keys deployed
  | 'denied' // OS-level permission denied — re-allow in system settings
  | 'on'
  | 'off';

/**
 * Decode a URL-safe base64 VAPID public key into the raw bytes
 * PushManager.subscribe wants as `applicationServerKey`.
 */
export function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const normalized = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(normalized);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

/** Whether this browser exposes the push machinery at all. */
export function pushSupported(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    'serviceWorker' in navigator &&
    typeof window !== 'undefined' &&
    'PushManager' in window &&
    'Notification' in window
  );
}
