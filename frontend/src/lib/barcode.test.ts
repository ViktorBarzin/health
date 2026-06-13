import { describe, expect, it } from 'vitest';
import {
  isLikelyBarcode,
  normalizeBarcode,
  pickScanEngine,
  ScanDebouncer,
} from './barcode';

// Pure barcode/scan-state logic (no camera, no DOM). The live camera glue lives
// in BarcodeScanner.svelte and needs a real device to exercise — see the note in
// that component. Here we pin the decision/normalisation logic the component
// depends on.

describe('normalizeBarcode', () => {
  it('strips whitespace and non-digits', () => {
    expect(normalizeBarcode(' 3017624010701 ')).toBe('3017624010701');
    expect(normalizeBarcode('301-762-401')).toBe('301762401');
  });

  it('returns empty string for no digits', () => {
    expect(normalizeBarcode('abc')).toBe('');
    expect(normalizeBarcode('')).toBe('');
  });
});

describe('isLikelyBarcode', () => {
  it('accepts 6–14 digit codes (EAN-8/EAN-13/UPC)', () => {
    expect(isLikelyBarcode('12345678')).toBe(true); // EAN-8
    expect(isLikelyBarcode('3017624010701')).toBe(true); // EAN-13
    expect(isLikelyBarcode('012345678905')).toBe(true); // UPC-A
  });

  it('rejects too-short, too-long, or non-numeric', () => {
    expect(isLikelyBarcode('12345')).toBe(false); // 5 digits
    expect(isLikelyBarcode('123456789012345')).toBe(false); // 15 digits
    expect(isLikelyBarcode('not-a-code')).toBe(false);
    expect(isLikelyBarcode('')).toBe(false);
  });
});

describe('pickScanEngine', () => {
  it('prefers the native BarcodeDetector when available', () => {
    expect(pickScanEngine({ hasBarcodeDetector: true })).toBe('native');
  });

  it('falls back to zxing when BarcodeDetector is absent', () => {
    expect(pickScanEngine({ hasBarcodeDetector: false })).toBe('zxing');
  });
});

describe('ScanDebouncer', () => {
  it('accepts the first decode of a code', () => {
    const d = new ScanDebouncer();
    expect(d.shouldAccept('3017624010701', 1000)).toBe(true);
  });

  it('rejects the same code within the window (camera fires many frames)', () => {
    const d = new ScanDebouncer(1500);
    expect(d.shouldAccept('3017624010701', 1000)).toBe(true);
    expect(d.shouldAccept('3017624010701', 1800)).toBe(false); // 800ms later
    expect(d.shouldAccept('3017624010701', 2000)).toBe(false); // 1000ms later
  });

  it('accepts the same code again after the window elapses', () => {
    const d = new ScanDebouncer(1500);
    expect(d.shouldAccept('3017624010701', 1000)).toBe(true);
    expect(d.shouldAccept('3017624010701', 2600)).toBe(true); // 1600ms later
  });

  it('accepts a different code immediately', () => {
    const d = new ScanDebouncer(1500);
    expect(d.shouldAccept('3017624010701', 1000)).toBe(true);
    expect(d.shouldAccept('0123456789012', 1100)).toBe(true);
  });

  it('reset() clears the debounce so the same code is accepted again', () => {
    const d = new ScanDebouncer(1500);
    expect(d.shouldAccept('3017624010701', 1000)).toBe(true);
    d.reset();
    expect(d.shouldAccept('3017624010701', 1100)).toBe(true);
  });
});
