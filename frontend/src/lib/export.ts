// Pure client-side helpers for the full-data Export flow (#19, ADR-0006).
//
// The Export itself is served by the backend as a streamed ZIP
// (GET /api/export). The browser only needs to (a) name the saved file and
// (b) trigger the download. The filename comes from the response's
// Content-Disposition header; this module is the PURE, DOM-free parser for it
// (the DOM trigger lives in api.ts). Mirrors the repo's "pure helper + test"
// convention (e.g. lib/fitbod.ts).

/** A sensible default archive name when the server doesn't send one. */
export const DEFAULT_EXPORT_FILENAME = 'health-export.zip';

/**
 * Extract the download filename from a Content-Disposition header value.
 *
 * Handles the common shapes the backend and proxies emit:
 *   - attachment; filename="health-export-alice-20260613-101500.zip"
 *   - attachment; filename=health-export.zip (unquoted)
 *   - RFC 5987 attachment; filename*=UTF-8''health%2Dexport.zip (preferred
 *     when present — it's percent-decoded)
 *
 * Returns {@link DEFAULT_EXPORT_FILENAME} when the header is missing/blank or
 * carries no usable filename, so the caller always has a name to save under.
 */
export function filenameFromContentDisposition(
  header: string | null | undefined,
): string {
  if (!header) return DEFAULT_EXPORT_FILENAME;

  // RFC 5987 extended form wins when present (filename*=charset''value).
  const extended = /filename\*\s*=\s*(?:[\w-]+'[^']*'|)([^;]+)/i.exec(header);
  if (extended && extended[1]) {
    const raw = extended[1].trim().replace(/^"|"$/g, '');
    try {
      const decoded = decodeURIComponent(raw);
      if (decoded) return decoded;
    } catch {
      // Fall through to the plain filename below on a malformed encoding.
    }
  }

  // Plain filename= (quoted or not). Avoid matching the extended filename*=.
  const plain = /filename\s*=\s*("?)([^";]+)\1/i.exec(header);
  if (plain && plain[2]) {
    const name = plain[2].trim();
    if (name) return name;
  }

  return DEFAULT_EXPORT_FILENAME;
}
