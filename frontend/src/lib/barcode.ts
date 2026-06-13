// Pure barcode/scan-state logic for the PWA scanner (#22).
//
// No camera, no DOM, no fetch — just the decisions the BarcodeScanner component
// depends on, kept here so they're unit-testable in node (the live camera needs a
// real device; BarcodeScanner.svelte carries the glue + a note). Mirrors the
// backend's `is_valid_barcode` so the client rejects obvious junk before a
// round-trip.

/** Which scan engine to drive (see pickScanEngine). */
export type ScanEngine = 'native' | 'zxing';

/** Strip a decoded value to digits only (barcodes are numeric: EAN/UPC). */
export function normalizeBarcode(raw: string): string {
  return raw.replace(/\D/g, '');
}

/**
 * True for a plausible retail barcode: 6–14 digits (covers EAN-8, EAN-13,
 * UPC-A/E). Matches the backend's barcode guard so the client and server agree.
 */
export function isLikelyBarcode(code: string): boolean {
  return /^\d{6,14}$/.test(code);
}

/**
 * Choose the scan engine: the browser's native `BarcodeDetector` when present
 * (zero bundle cost, hardware-accelerated — Chrome/Android), else the bundled
 * `@zxing/browser` fallback (iOS Safari and other browsers without the API).
 */
export function pickScanEngine(env: { hasBarcodeDetector: boolean }): ScanEngine {
  return env.hasBarcodeDetector ? 'native' : 'zxing';
}

/** Detect the native BarcodeDetector at runtime (false in SSR / unsupported). */
export function hasNativeBarcodeDetector(): boolean {
  return typeof globalThis !== 'undefined' && 'BarcodeDetector' in globalThis;
}

/**
 * Debounce repeated decodes of the same barcode. A camera scanner fires the same
 * code on many consecutive frames; without this we'd hit the resolve endpoint
 * dozens of times per scan. The same code is accepted at most once per
 * `windowMs`; a different code is accepted immediately (so re-aiming at a new
 * product is instant). `reset()` clears state (e.g. when the scanner restarts).
 */
export class ScanDebouncer {
  private last: { code: string; at: number } | null = null;

  constructor(private readonly windowMs: number = 1500) {}

  shouldAccept(code: string, now: number): boolean {
    if (
      this.last !== null &&
      this.last.code === code &&
      now - this.last.at < this.windowMs
    ) {
      return false;
    }
    this.last = { code, at: now };
    return true;
  }

  reset(): void {
    this.last = null;
  }
}
