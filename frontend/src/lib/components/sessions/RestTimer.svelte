<script lang="ts">
  import {
    idleTimer,
    restTimerReducer,
    type RestTimerState,
  } from '$lib/rest-timer';

  // Rest timer (#7): a mobile-first, non-blocking countdown that auto-starts when
  // a Set is logged and fires a sound + vibration on completion. The COUNTDOWN
  // LOGIC is the pure reducer (lib/rest-timer.ts); this component owns only the
  // side-effects — a 250ms tick interval, the WebAudio beep, navigator.vibrate,
  // and the `onendsat` signal the page turns into a server-scheduled Web Push
  // (the locked-phone / Apple Watch cue, ADR-0010).
  //
  // Controlled by the parent via `startSignal`: bumping it (with a duration)
  // starts/restarts the timer. The bar pins above the finish bar and never blocks
  // logging — the user keeps adding sets while it counts down.

  let {
    startSignal = 0,
    startDuration = 120,
    onendsat,
  }: {
    startSignal?: number;
    startDuration?: number;
    /**
     * Fires whenever the countdown's end instant changes: an epoch-ms when a
     * countdown is (re)started or adjusted, null when it's skipped — or when
     * it completes with the page VISIBLE (the in-page cue just fired, so the
     * parent cancels the scheduled server push; a frozen/locked page never
     * reaches this, which is exactly when the push should get through —
     * ADR-0010).
     */
    onendsat?: (endsAtMs: number | null) => void;
  } = $props();

  let timer = $state<RestTimerState>(idleTimer());
  let interval: ReturnType<typeof setInterval> | null = null;

  // React to the parent's start signal (a monotonically increasing counter). Each
  // new value (re)starts the countdown for `startDuration` seconds.
  let lastSignal = $state(0);
  $effect(() => {
    if (startSignal > 0 && startSignal !== lastSignal) {
      lastSignal = startSignal;
      timer = restTimerReducer(timer, {
        type: 'start',
        durationSec: startDuration,
        now: Date.now(),
      });
      onendsat?.(timer.endsAt);
      ensureTicking();
    }
  });

  function ensureTicking() {
    if (interval !== null) return;
    interval = setInterval(() => {
      timer = restTimerReducer(timer, { type: 'tick', now: Date.now() });
      if (timer.justCompleted) onComplete();
      if (!timer.running) stopTicking();
    }, 250);
  }

  function stopTicking() {
    if (interval !== null) {
      clearInterval(interval);
      interval = null;
    }
  }

  function onComplete() {
    beep();
    // Vibrate where supported (Android/Chrome); a no-op on iOS Safari.
    try {
      navigator.vibrate?.([200, 80, 200]);
    } catch {
      // ignore — vibration is best-effort
    }
    // The user just saw/heard the in-page cue — cancel the server push so a
    // duplicate banner doesn't land on a lit screen. A locked phone freezes
    // this code, so the push correctly survives there (ADR-0010).
    if (typeof document !== 'undefined' && document.visibilityState === 'visible') {
      onendsat?.(null);
    }
  }

  // A short two-tone beep via the Web Audio API (no audio asset to bundle/load).
  function beep() {
    try {
      const AudioCtx =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext?: typeof AudioContext })
          .webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const play = (freq: number, start: number, dur: number) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = freq;
        osc.type = 'sine';
        gain.gain.setValueAtTime(0.0001, ctx.currentTime + start);
        gain.gain.exponentialRampToValueAtTime(0.3, ctx.currentTime + start + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
        osc.connect(gain).connect(ctx.destination);
        osc.start(ctx.currentTime + start);
        osc.stop(ctx.currentTime + start + dur);
      };
      play(880, 0, 0.18);
      play(1320, 0.2, 0.22);
      setTimeout(() => ctx.close().catch(() => {}), 800);
    } catch {
      // ignore — audio is best-effort (autoplay policy / unsupported)
    }
  }

  function skip() {
    timer = restTimerReducer(timer, { type: 'skip' });
    stopTicking();
    onendsat?.(null);
  }

  function adjust(deltaSec: number) {
    timer = restTimerReducer(timer, { type: 'adjust', deltaSec, now: Date.now() });
    // Subtracting can drive the timer to zero — fire completion just like a tick.
    if (timer.justCompleted) onComplete();
    else onendsat?.(timer.endsAt);
    if (timer.running) ensureTicking();
    else stopTicking();
  }

  $effect(() => () => stopTicking()); // cleanup on unmount

  let mmss = $derived(
    `${Math.floor(timer.remainingSec / 60)}:${String(timer.remainingSec % 60).padStart(2, '0')}`,
  );
  let progress = $derived(
    timer.durationSec > 0 ? timer.remainingSec / timer.durationSec : 0,
  );
</script>

{#if timer.running}
  <div class="flex items-center gap-3 px-4 py-2.5 rounded-xl bg-surface-800 border border-primary-500/30 shadow-lg">
    <!-- Progress ring -->
    <div class="relative w-9 h-9 shrink-0">
      <svg class="w-9 h-9 -rotate-90" viewBox="0 0 36 36">
        <circle cx="18" cy="18" r="15" fill="none" stroke="currentColor" class="text-surface-700" stroke-width="3" />
        <circle
          cx="18" cy="18" r="15" fill="none" stroke="currentColor" class="text-primary-400"
          stroke-width="3" stroke-linecap="round"
          stroke-dasharray={2 * Math.PI * 15}
          stroke-dashoffset={2 * Math.PI * 15 * (1 - progress)}
        />
      </svg>
    </div>
    <div class="flex-1 min-w-0">
      <p class="text-[0.65rem] uppercase tracking-wide text-surface-500 font-semibold">Rest</p>
      <p class="text-lg font-bold text-surface-100 tabular-nums leading-tight">{mmss}</p>
    </div>
    <button onclick={() => adjust(-15)} class="px-2.5 py-1.5 rounded-lg bg-surface-700 hover:bg-surface-600 text-surface-200 text-xs font-medium">−15s</button>
    <button onclick={() => adjust(15)} class="px-2.5 py-1.5 rounded-lg bg-surface-700 hover:bg-surface-600 text-surface-200 text-xs font-medium">+15s</button>
    <button onclick={skip} class="px-3 py-1.5 rounded-lg bg-primary-500/20 hover:bg-primary-500/30 text-primary-300 text-xs font-semibold">Skip</button>
  </div>
{/if}
