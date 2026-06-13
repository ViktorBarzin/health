// Screen Wake Lock helper (#7) — keep the screen awake during an active Session.
//
// Wraps the Screen Wake Lock API with a graceful fallback where it's unsupported
// (e.g. older Safari) — the caller just gets a no-op and the screen sleeps as
// normal. The lock is auto-reacquired when the tab becomes visible again
// (browsers release it on visibility change / tab switch).
//
// Not a Svelte rune store on purpose: it's a thin imperative wrapper a component
// drives from $effect, so it stays unit-reasoned and DOM-only.

/** Whether the Screen Wake Lock API is available in this browser. */
export function wakeLockSupported(): boolean {
  return typeof navigator !== 'undefined' && 'wakeLock' in navigator;
}

export interface WakeLockHandle {
  /** Release the lock and stop reacquiring it. Safe to call repeatedly. */
  release: () => void;
  /** True if the API was available and a lock could be requested. */
  readonly supported: boolean;
}

/**
 * Request a screen wake lock and keep it held until {@link WakeLockHandle.release}.
 *
 * Re-acquires automatically when the page returns to the foreground (the browser
 * drops the lock on tab switch / minimise). Returns a handle whose `supported`
 * flag is false — with a no-op `release` — when the API is unavailable, so
 * callers never branch on feature detection themselves.
 */
export function requestWakeLock(): WakeLockHandle {
  if (!wakeLockSupported()) {
    return { release: () => {}, supported: false };
  }

  let sentinel: WakeLockSentinel | null = null;
  let active = true;

  const acquire = async () => {
    if (!active) return;
    try {
      sentinel = await navigator.wakeLock.request('screen');
    } catch {
      // Request can reject (e.g. not visible, low battery) — ignore; the
      // visibility handler retries when the page is foregrounded again.
      sentinel = null;
    }
  };

  const onVisibility = () => {
    if (active && document.visibilityState === 'visible' && sentinel === null) {
      void acquire();
    }
  };

  document.addEventListener('visibilitychange', onVisibility);
  void acquire();

  return {
    supported: true,
    release: () => {
      active = false;
      document.removeEventListener('visibilitychange', onVisibility);
      sentinel?.release().catch(() => {});
      sentinel = null;
    },
  };
}
