// Pure client-side helpers for the Fitbod CSV import flow (#9).
//
// The server is the authority on parsing (app/services/fitbod_parser.py); this
// is only a fast, pure pre-check so the upload UI can reject an obviously-wrong
// file (e.g. an Apple Health export, or a random spreadsheet) before a round
// trip, and phrase a clear message. Mirrors the server's required-column rule:
// a Fitbod export has at least Date, Exercise and Reps columns, matched by NAME.

/** Normalise a header cell the way the server does (lower, trim, de-quote). */
function normHeader(cell: string): string {
  return cell.trim().replace(/^"|"$/g, '').trim().toLowerCase();
}

/**
 * True if the first CSV line looks like a Fitbod "Export Workout Data" header
 * — it carries at least Date, Exercise and Reps columns. Tolerant of column
 * order, extra columns, casing and surrounding whitespace (matches by name).
 */
export function looksLikeFitbodCsv(text: string): boolean {
  const firstLine = text.split(/\r?\n/, 1)[0] ?? '';
  if (!firstLine.trim()) return false;
  const headers = firstLine.split(',').map(normHeader);
  const has = (...names: string[]) => headers.some((h) => names.includes(h));
  return (
    has('date') &&
    has('exercise', 'exercise name') &&
    has('reps')
  );
}
