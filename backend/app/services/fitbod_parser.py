"""Pure parser for a Fitbod "Export Workout Data" CSV.

The only source of set-level strength history we can import, so it seeds the
Progression/Recovery engine. This module is **pure** (no DB, no clock, no IO
beyond reading the text it is handed) so the parsing rules are unit-tested in
isolation; the DB glue (idempotent write into Sessions/Sets, the Fitbod Source,
the import batch) lives in :mod:`app.services.fitbod_import`.

Fitbod's export format (verified against real-export parsers — the Mikulas
fitbod→hevy gist and rhnfzl/fitbod-report, 2026-06):

    Date,Exercise,Reps,Weight(kg),Duration(s),Distance(m),Incline,Resistance,isWarmup,Note,multiplier
    2021-12-27 10:02:51 +0000,Back Squat,5,100.5,0.0,0.0,0.0,0.0,false,Good form,1.0

Robustness rules (the acceptance criteria — "parse by column NAME, not
position"; the exact columns vary by app version):

* **Columns are matched by header name**, case-insensitively, tolerant of
  surrounding whitespace. Extra columns are ignored; absent optional columns are
  treated as blank. ``Date``, ``Exercise`` and ``Reps`` are required headers
  (without them the file isn't a Fitbod export and we raise).
* **Units live in the weight header's suffix** — ``Weight(kg)`` vs
  ``Weight(lbs)``/``Weight(lb)`` (Fitbod stamps the user's configured unit into
  the column name, the same convention FitNotes uses). We read the suffix and
  convert pounds → kilograms; an unmarked ``Weight`` column is assumed kg.
* **Date** parses ``%Y-%m-%d %H:%M:%S %z`` (e.g. ``2021-12-27 10:02:51 +0000``);
  a couple of seen fallbacks (no timezone; ISO ``T`` separator) are tolerated.
  Every set row in one Fitbod workout shares the same Date timestamp, so the
  timestamp is exactly the Session key.
* **Warmup** flag: the ``isWarmup`` column is the literal string ``true`` /
  ``false`` (any non-``false`` truthy value counts as warmup) → ``set_type`` is
  ``warmup`` else ``normal``.
* **Non-strength rows are skipped, not turned into garbage Sets.** A row with no
  positive weight *and* no positive reps is a cardio / distance / duration-only
  entry (Fitbod logs treadmill runs etc. with Duration/Distance set and
  weight=reps=0). It records a ``skipped`` reason rather than an empty Set.
  Bodyweight strength (weight 0 but reps > 0, e.g. pull-ups) is a real Set and is
  kept.
* Quoted fields, embedded commas and blank notes are handled by the stdlib
  ``csv`` reader.

Grouping: rows are grouped into :class:`ParsedSession` objects keyed by their
Date timestamp; ``started_at`` is that timestamp. Within a Session, sets keep
their CSV order via ``order_index`` (0-based, gap-free). This mirrors the live
logger's order contract so imported Sessions read identically to logged ones.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime

# 1 lb = 0.45359237 kg (exact, international avoirdupois pound).
_LB_TO_KG = 0.45359237

# Accepted Date formats, tried in order. The first is Fitbod's actual export
# format; the others are defensive fallbacks for hand-edited / older files.
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S %z",  # 2021-12-27 10:02:51 +0000  (Fitbod's real format)
    "%Y-%m-%d %H:%M:%S",  # no timezone
    "%Y-%m-%dT%H:%M:%S%z",  # ISO 'T' separator with tz
    "%Y-%m-%dT%H:%M:%S",  # ISO 'T' separator, no tz
)


class FitbodParseError(ValueError):
    """The uploaded file is not a recognisable Fitbod workout CSV."""


@dataclass(frozen=True)
class ParsedSet:
    """One performed Set parsed from a Fitbod CSV row (pre-matching).

    ``exercise_name`` is the raw Fitbod name — matching to a library Exercise
    happens later (:mod:`app.services.matcher`). ``weight_kg`` is already
    converted to kilograms. ``is_warmup`` maps to ``set_type`` at write time.
    ``order_index`` is the 0-based position within its Session.
    """

    exercise_name: str
    weight_kg: float
    reps: int
    is_warmup: bool
    order_index: int


@dataclass(frozen=True)
class ParsedSession:
    """A Session parsed from the CSV: a performed timestamp + ordered Sets."""

    started_at: datetime
    sets: tuple[ParsedSet, ...]

    @property
    def exercise_names(self) -> set[str]:
        """The distinct raw Fitbod exercise names appearing in this Session."""
        return {s.exercise_name for s in self.sets}


@dataclass
class ParseResult:
    """Outcome of parsing a Fitbod CSV: the Sessions plus a skip tally."""

    sessions: list[ParsedSession] = field(default_factory=list)
    skipped_rows: int = 0
    total_rows: int = 0

    @property
    def set_count(self) -> int:
        return sum(len(s.sets) for s in self.sessions)

    @property
    def exercise_names(self) -> list[str]:
        """All distinct raw exercise names across every Session, sorted."""
        names: set[str] = set()
        for session in self.sessions:
            names |= session.exercise_names
        return sorted(names)

    def set_counts_by_name(self) -> dict[str, int]:
        """How many parsed (kept) Sets carry each raw Fitbod exercise name."""
        counts: dict[str, int] = {}
        for session in self.sessions:
            for s in session.sets:
                counts[s.exercise_name] = counts.get(s.exercise_name, 0) + 1
        return counts


def _normalise_header(header: str) -> str:
    """Lower-case, trim, and strip surrounding quotes from a header cell."""
    return header.strip().strip('"').strip().lower()


def _find_column(headers: list[str], *candidates: str) -> int | None:
    """Index of the first header equal to one of ``candidates`` (normalised).

    Matching is by NAME, never position — Fitbod reorders/adds columns across
    app versions. Returns ``None`` if no candidate is present.
    """
    wanted = [c.lower() for c in candidates]
    for idx, header in enumerate(headers):
        if _normalise_header(header) in wanted:
            return idx
    return None


def _weight_unit_is_pounds(headers: list[str]) -> bool:
    """Whether the weight column header marks pounds rather than kilograms.

    The unit is encoded in the header suffix: ``Weight(kg)`` vs
    ``Weight(lbs)``/``Weight(lb)``. An unmarked ``Weight`` is assumed kg.
    """
    for header in headers:
        norm = _normalise_header(header)
        if norm.startswith("weight"):
            return "lb" in norm  # matches "lb" and "lbs"
    return False


def _cell(row: list[str], idx: int | None) -> str:
    """The trimmed value at ``idx`` in ``row``, or empty string if absent."""
    if idx is None or idx >= len(row):
        return ""
    return row[idx].strip()


def _parse_float(value: str) -> float:
    """Parse a numeric cell to float; blank/garbage → 0.0 (never raises)."""
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def _parse_int(value: str) -> int:
    """Parse an integer rep count; tolerates ``5.0`` and blanks → 0."""
    if not value:
        return 0
    try:
        return int(round(float(value)))
    except ValueError:
        return 0


def _parse_date(value: str) -> datetime | None:
    """Parse a Fitbod Date cell with the accepted formats; None if unparseable."""
    value = value.strip().strip('"').strip()
    if not value:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    # Last resort: Python's own ISO parser (handles offsets like +00:00).
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_warmup(value: str) -> bool:
    """Interpret the isWarmup cell: any non-``false`` truthy string is a warmup.

    Fitbod writes ``true``/``false``; we also accept ``1``/``yes`` defensively.
    A blank cell is NOT a warmup (the common case is a working set).
    """
    norm = value.strip().lower()
    if not norm:
        return False
    return norm not in ("false", "0", "no", "f", "n")


def parse_fitbod_csv(text: str) -> ParseResult:
    """Parse a Fitbod workout-history CSV into ordered :class:`ParsedSession`s.

    Pure: takes the decoded CSV text, returns the parsed structure. Groups rows
    into Sessions by their Date timestamp (every set in one Fitbod workout shares
    it), converts weights to kilograms, flags warmups, and skips non-strength
    rows. Raises :class:`FitbodParseError` if the required Date/Exercise/Reps
    headers are missing (i.e. it isn't a Fitbod export).
    """
    # ``io.StringIO`` + csv.reader handles quoting, embedded commas and CRLF.
    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration as exc:
        raise FitbodParseError("The CSV file is empty.") from exc

    date_col = _find_column(headers, "date")
    exercise_col = _find_column(headers, "exercise", "exercise name")
    reps_col = _find_column(headers, "reps")
    weight_col = _find_column(
        headers, "weight(kg)", "weight(lbs)", "weight(lb)", "weight"
    )
    warmup_col = _find_column(headers, "iswarmup", "warmup", "is warmup")

    if date_col is None or exercise_col is None or reps_col is None:
        raise FitbodParseError(
            "This does not look like a Fitbod export — expected at least "
            "'Date', 'Exercise' and 'Reps' columns. Use Fitbod → Settings → "
            "Export Workout Data."
        )

    pounds = _weight_unit_is_pounds(headers)

    # Group sets by their workout timestamp, preserving first-seen order so the
    # resulting Sessions list is chronologically stable for the same file.
    grouped: dict[datetime, list[ParsedSet]] = {}
    order: list[datetime] = []
    skipped = 0
    total = 0

    for raw_row in reader:
        # Skip wholly blank lines (trailing newline, hand-edited gaps).
        if not raw_row or all(not cell.strip() for cell in raw_row):
            continue
        total += 1

        started_at = _parse_date(_cell(raw_row, date_col))
        exercise_name = _cell(raw_row, exercise_col)
        if started_at is None or not exercise_name:
            # No timestamp or no exercise name → unusable row.
            skipped += 1
            continue

        reps = _parse_int(_cell(raw_row, reps_col))
        weight = _parse_float(_cell(raw_row, weight_col))
        if pounds:
            weight = round(weight * _LB_TO_KG, 4)

        # Skip non-strength rows: no positive weight AND no positive reps is a
        # cardio / distance / duration-only entry, not a real Set. Bodyweight
        # strength (weight 0, reps > 0) is kept.
        if weight <= 0 and reps <= 0:
            skipped += 1
            continue

        is_warmup = _is_warmup(_cell(raw_row, warmup_col))

        bucket = grouped.setdefault(started_at, [])
        if not bucket:
            order.append(started_at)
        bucket.append(
            ParsedSet(
                exercise_name=exercise_name,
                weight_kg=max(weight, 0.0),
                reps=max(reps, 0),
                is_warmup=is_warmup,
                order_index=len(bucket),  # 0-based within the Session
            )
        )

    sessions = [
        ParsedSession(started_at=ts, sets=tuple(grouped[ts])) for ts in order
    ]
    return ParseResult(sessions=sessions, skipped_rows=skipped, total_rows=total)
