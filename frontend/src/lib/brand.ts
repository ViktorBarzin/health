// Product identity — the single swappable wordmark token (ADR-0008).
//
// The product name is deliberately DEFERRED: every surface (header, sidebar,
// PWA install name, splash) reads the name from here, so renaming later is a
// one-line change rather than a hunt-and-replace. Until a name is chosen this
// is the neutral working wordmark.

/** Full product name shown in the header / sidebar / install prompts. */
export const PRODUCT_NAME = 'Health';

/** Short form for tight spots (tab title, compact header). */
export const PRODUCT_SHORT = 'Health';

/** One-line descriptor; null hides the tagline. */
export const PRODUCT_TAGLINE: string | null = 'Train · Eat · Recover';
