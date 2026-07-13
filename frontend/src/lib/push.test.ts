// Pure Web Push helpers (ADR-0010).

import { describe, expect, it } from 'vitest';
import { urlBase64ToUint8Array } from './push';

describe('urlBase64ToUint8Array', () => {
  it('decodes URL-safe base64 (with -/_ and no padding) to the raw bytes', () => {
    // "hello" → aGVsbG8 (unpadded)
    expect([...urlBase64ToUint8Array('aGVsbG8')]).toEqual([104, 101, 108, 108, 111]);
  });

  it('maps URL-safe alphabet back to standard base64', () => {
    // 0xfb 0xff → standard "+/8=" → URL-safe "-_8"
    expect([...urlBase64ToUint8Array('-_8')]).toEqual([0xfb, 0xff]);
  });

  it('round-trips a realistic 65-byte uncompressed P-256 point', () => {
    const bytes = new Uint8Array(65).map((_, i) => (i * 7) % 256);
    let bin = '';
    for (const b of bytes) bin += String.fromCharCode(b);
    const urlSafe = btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    expect([...urlBase64ToUint8Array(urlSafe)]).toEqual([...bytes]);
  });
});
