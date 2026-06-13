<script lang="ts">
  import {
    ScanDebouncer,
    hasNativeBarcodeDetector,
    isLikelyBarcode,
    normalizeBarcode,
    pickScanEngine,
    type ScanEngine,
  } from '$lib/barcode';

  // Live barcode scanner for the PWA (#22). Points the rear camera at a product
  // barcode and emits the decoded value via `ondetected`. Uses the browser's
  // native BarcodeDetector when available (Chrome/Android — zero bundle cost,
  // hardware-accelerated), and falls back to @zxing/browser otherwise (iOS
  // Safari and others). On a camera-permission failure or unsupported
  // environment it surfaces a clear message and the caller offers manual
  // entry/search instead.
  //
  // NOTE: the live camera path can only be exercised on a real device (getUserMedia
  // + a physical barcode). The DECISION/normalisation logic it relies on
  // (engine pick, debounce, barcode validation) is pure and unit-tested in
  // barcode.test.ts; this component is the thin DOM/camera glue around it.

  let {
    active = false,
    ondetected,
    onfallback,
  }: {
    /** When true, the camera is started; when false, it's stopped + released. */
    active?: boolean;
    /** Called with a normalised, plausible barcode on a successful scan. */
    ondetected: (code: string) => void;
    /** Called when the camera can't be used, so the caller can offer manual entry. */
    onfallback?: (reason: string) => void;
  } = $props();

  let videoEl: HTMLVideoElement | null = $state(null);
  let status = $state<'idle' | 'starting' | 'scanning' | 'error'>('idle');
  let errorMsg = $state('');

  const debouncer = new ScanDebouncer(1500);

  // Engine + teardown handles. zxing returns IScannerControls; native uses a
  // MediaStream + a rAF/interval detect loop.
  let engine: ScanEngine | null = null;
  let stream: MediaStream | null = null;
  let zxingControls: { stop: () => void } | null = null;
  let detectTimer: ReturnType<typeof setInterval> | null = null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let nativeDetector: any = null;
  let stopped = false;

  // React to `active`: start when turned on, stop when turned off / unmounted.
  $effect(() => {
    if (active) {
      start();
    } else {
      stop();
    }
    return () => stop();
  });

  function accept(raw: string) {
    const code = normalizeBarcode(raw);
    if (!isLikelyBarcode(code)) return;
    if (!debouncer.shouldAccept(code, Date.now())) return;
    ondetected(code);
  }

  function fail(reason: string) {
    status = 'error';
    errorMsg = reason;
    stop();
    onfallback?.(reason);
  }

  async function start() {
    if (status === 'scanning' || status === 'starting') return;
    stopped = false;
    status = 'starting';
    errorMsg = '';
    debouncer.reset();

    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      fail('Camera not available on this device.');
      return;
    }

    engine = pickScanEngine({ hasBarcodeDetector: hasNativeBarcodeDetector() });
    try {
      if (engine === 'native') {
        await startNative();
      } else {
        await startZxing();
      }
    } catch (err) {
      const name = err instanceof Error ? err.name : '';
      if (name === 'NotAllowedError' || name === 'SecurityError') {
        fail('Camera permission denied. Enter the barcode or search instead.');
      } else if (name === 'NotFoundError') {
        fail('No camera found. Enter the barcode or search instead.');
      } else {
        fail('Could not start the camera. Enter the barcode or search instead.');
      }
    }
  }

  async function startNative() {
    // Rear camera preferred; the detector reads frames off the live <video>.
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' },
      audio: false,
    });
    if (stopped) return releaseStream();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const BD = (globalThis as any).BarcodeDetector;
    nativeDetector = new BD({
      formats: ['ean_13', 'ean_8', 'upc_a', 'upc_e'],
    });
    if (videoEl) {
      videoEl.srcObject = stream;
      await videoEl.play().catch(() => {});
    }
    status = 'scanning';
    // Poll a few times a second; cheaper than every rAF and plenty responsive.
    detectTimer = setInterval(detectNativeFrame, 250);
  }

  async function detectNativeFrame() {
    if (!nativeDetector || !videoEl || videoEl.readyState < 2) return;
    try {
      const codes = await nativeDetector.detect(videoEl);
      for (const c of codes) {
        if (c?.rawValue) accept(String(c.rawValue));
      }
    } catch {
      // Transient detect errors (e.g. a frame not ready) are ignored.
    }
  }

  async function startZxing() {
    // Dynamic import so the fallback library is only fetched when actually used
    // (native-capable browsers never pay for it).
    const { BrowserMultiFormatReader } = await import('@zxing/browser');
    const reader = new BrowserMultiFormatReader(undefined, {
      delayBetweenScanAttempts: 250,
    });
    if (stopped) return;
    status = 'scanning';
    // `undefined` deviceId → zxing auto-selects the environment-facing camera and
    // renders into our <video>. The callback fires per decode (result may be
    // undefined when no code is in frame).
    zxingControls = await reader.decodeFromVideoDevice(
      undefined,
      videoEl ?? undefined,
      (result) => {
        const text = result?.getText?.();
        if (text) accept(text);
      },
    );
  }

  function releaseStream() {
    if (stream) {
      for (const track of stream.getTracks()) track.stop();
      stream = null;
    }
  }

  function stop() {
    stopped = true;
    if (detectTimer) {
      clearInterval(detectTimer);
      detectTimer = null;
    }
    nativeDetector = null;
    if (zxingControls) {
      try {
        zxingControls.stop();
      } catch {
        // already stopped
      }
      zxingControls = null;
    }
    releaseStream();
    if (videoEl) videoEl.srcObject = null;
    if (status !== 'error') status = 'idle';
  }
</script>

<div class="space-y-3">
  {#if status === 'error'}
    <div class="p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-center">
      <p class="text-sm text-red-300">{errorMsg}</p>
    </div>
  {:else}
    <div class="relative aspect-[4/3] w-full overflow-hidden rounded-xl bg-black">
      <!-- svelte-ignore a11y_media_has_caption -->
      <video bind:this={videoEl} class="h-full w-full object-cover" playsinline muted></video>
      <!-- A simple reticle to aim the barcode. -->
      <div class="pointer-events-none absolute inset-0 flex items-center justify-center">
        <div class="h-24 w-3/4 rounded-lg border-2 border-primary-400/80 shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]"></div>
      </div>
      {#if status === 'starting'}
        <div class="absolute inset-0 flex items-center justify-center">
          <div class="w-6 h-6 border-2 border-white/60 border-t-transparent rounded-full animate-spin"></div>
        </div>
      {/if}
    </div>
    <p class="text-center text-xs text-surface-500">
      {status === 'scanning' ? 'Point the camera at a barcode' : 'Starting camera…'}
    </p>
  {/if}
</div>
