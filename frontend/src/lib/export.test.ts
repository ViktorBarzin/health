import { describe, expect, it } from 'vitest';
import {
  DEFAULT_EXPORT_FILENAME,
  filenameFromContentDisposition,
} from './export';

describe('filenameFromContentDisposition', () => {
  it('reads a quoted filename', () => {
    expect(
      filenameFromContentDisposition(
        'attachment; filename="health-export-alice-20260613-101500.zip"',
      ),
    ).toBe('health-export-alice-20260613-101500.zip');
  });

  it('reads an unquoted filename', () => {
    expect(
      filenameFromContentDisposition('attachment; filename=health-export.zip'),
    ).toBe('health-export.zip');
  });

  it('prefers the RFC 5987 extended filename and percent-decodes it', () => {
    expect(
      filenameFromContentDisposition(
        "attachment; filename=\"fallback.zip\"; filename*=UTF-8''health%2Dexport%2Dbob.zip",
      ),
    ).toBe('health-export-bob.zip');
  });

  it('falls back to the default when the header is missing', () => {
    expect(filenameFromContentDisposition(null)).toBe(DEFAULT_EXPORT_FILENAME);
    expect(filenameFromContentDisposition(undefined)).toBe(
      DEFAULT_EXPORT_FILENAME,
    );
    expect(filenameFromContentDisposition('')).toBe(DEFAULT_EXPORT_FILENAME);
  });

  it('falls back to the default when there is no filename token', () => {
    expect(filenameFromContentDisposition('attachment')).toBe(
      DEFAULT_EXPORT_FILENAME,
    );
  });

  it('is tolerant of surrounding whitespace and casing', () => {
    expect(
      filenameFromContentDisposition('Attachment;  FileName =  "x.zip" '),
    ).toBe('x.zip');
  });
});
