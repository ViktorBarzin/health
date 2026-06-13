"""Full per-user data Export — the bounded-memory archive engine (ADR-0006).

CONTEXT.md ("Export"): "A user's full personal archive — every Session, Set,
Workout, Metric, and Diary Entry — as downloadable JSON + CSV. The data-ownership
guarantee of a self-hosted platform." ADR-0006 frames Export as the read-side
mirror of the ingest API.

Two hard requirements shape this module:

1. **Per-user isolation is security-critical.** Every record type's query filters
   by the requesting user's id. Tables that carry ``user_id`` filter directly;
   child tables with no ``user_id`` of their own (``training_sets`` via its
   Session, ``workout_route_points`` via its Workout) filter through a subquery of
   the parent rows that user owns. The shared Exercise library is NEVER exported
   as data — only the user's *custom* Exercises (``exercises.user_id == me``). The
   single source of every scope is the per-spec ``stmt_for`` callable here, so the
   isolation rule is reviewable in one place.

2. **It must stream — never buffer a table in memory.** Prod holds ~6.6M
   ``health_records`` for one user. So:
   * each record type is read through a **server-side cursor**
     (``AsyncSession.stream(...).partitions(chunk_size)``), yielding bounded
     chunks — we never call ``.all()`` on a multi-million-row table;
   * the ZIP is assembled on disk in a ``NamedTemporaryFile`` as we go (one CSV
     per record type + a single JSON document), and the JSON is written
     **incrementally** (open the array, stream rows comma-separated, close it) so
     even the JSON representation never holds a whole table in a Python list;
   * the finished temp file is streamed back to the client in fixed-size byte
     chunks, then deleted.

Archive layout (a single ZIP, ``health-export-<email>-<UTC-stamp>.zip``)::

    export.json                         # the full nested archive (manifest + all records)
    csv/sessions.csv
    csv/sets.csv
    csv/workouts.csv
    csv/workout_route_points.csv
    csv/health_records.csv              # the high-volume Metric table
    csv/category_records.csv            # categorical Metric samples (sleep, …)
    csv/activity_summaries.csv
    csv/programs.csv
    csv/program_days.csv
    csv/program_muscle_volumes.csv
    csv/personal_records.csv
    csv/custom_exercises.csv            # the user's OWN Exercises (not the shared library)
    csv/gym_profile.csv                 # the singleton, 0-or-1 row
    csv/diary_entries.csv               # ONLY if the nutrition tables exist (skipped otherwise)

The JSON document mirrors the CSVs: ``{"user": {...}, "generated_at": "...",
"records": {"<name>": [ ...rows... ], ..., "gym_profile": {...}|null,
"diary_entries": [...]?}}``. Sets are emitted both flat (``records.sets`` / the
CSV) and the Session retains its id, so the relationship is recoverable without
duplicating set rows under every session.

YAGNI (ADR-0006): a full archive download — not per-type selectable export, not
scheduling, not read-scoped tokens. Those are deliberately deferred.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import Select, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_summary import ActivitySummary
from app.models.category_record import CategoryRecord
from app.models.exercise import Exercise
from app.models.gym_profile import GymProfile
from app.models.health_record import HealthRecord
from app.models.personal_record import PersonalRecord
from app.models.program import Program, ProgramDay, ProgramMuscleVolume
from app.models.training_session import TrainingSession, TrainingSet
from app.models.user import User
from app.models.workout import Workout
from app.models.workout_route_point import WorkoutRoutePoint

# Rows fetched per server-side-cursor partition. Bounded so memory stays flat
# regardless of table size (6.6M health_records → ~660 partitions, never a list
# of 6.6M). Tuned for a sensible round-trip/overhead balance, not correctness.
DEFAULT_CHUNK_SIZE = 5_000

# Byte chunk size when streaming the finished temp-file ZIP back to the client.
_FILE_READ_CHUNK = 64 * 1024


def _to_jsonable(value: Any) -> Any:
    """Make a DB value JSON/CSV-safe.

    datetimes/dates → ISO 8601; JSON-native scalars (str/int/float/bool/None)
    and JSONB structures (``dict``/``list``, which ``json.dumps`` handles
    natively) pass through UNCHANGED — stringifying a dict here would emit a
    Python-repr ("{'a': 1}") instead of JSON, corrupting the archive. Everything
    else (notably UUID) is rendered by ``str`` so ids are stable strings across
    JSON and CSV.
    """
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool, dict, list)):
        return value
    return str(value)


def _csv_cell(value: Any) -> str:
    """Render one value for a CSV cell.

    Scalars use their JSON-able string form; JSONB structures (dict/list) are
    embedded as compact JSON text so a CSV column never silently loses data.
    """
    rendered = _to_jsonable(value)
    if isinstance(rendered, (dict, list)):
        return json.dumps(rendered, separators=(",", ":"))
    if rendered is None:
        return ""
    return str(rendered)


@dataclass(frozen=True)
class RecordSpec:
    """One exportable record type: its name, columns, and user-scoped query.

    ``stmt_for(user_id)`` is the SINGLE source of the per-user scope for this
    record type — direct ``user_id`` filter for owner tables, a parent-ownership
    subquery for child tables. ``columns`` is the ordered ``(header, attr)`` list
    projected into both the CSV row and the JSON object, so the two
    representations never drift; ``attr`` is the mapped attribute name on
    ``model`` (e.g. ``"metadata_"`` for the column DB-named ``metadata``).
    """

    name: str
    model: type
    columns: Sequence[tuple[str, str]]
    stmt_for: Callable[[int], Select]
    # Order rows deterministically (also makes tests stable).
    order_by: Sequence[Any] = field(default_factory=tuple)

    @property
    def headers(self) -> list[str]:
        return [header for header, _ in self.columns]

    @property
    def column_exprs(self) -> list[Any]:
        """The mapped column expressions, in ``columns`` order.

        Streaming explicit columns (rather than the whole ORM entity) is what
        makes JSONB values come back deserialized as dict/list — a server-side
        cursor over a full entity returns JSONB as a Python-repr *string*, which
        would corrupt the archive. So the export always projects these columns.
        """
        return [getattr(self.model, attr) for _, attr in self.columns]

    def row_to_dict(self, row: Any) -> dict[str, Any]:
        """Project a positional column ``Row`` into an ordered, JSON-able dict.

        Positional (``row[i]``) — not by name — because a column's result key is
        its DB name, which can differ from the mapped attribute (``metadata`` vs
        ``metadata_``); the projection order is fixed by ``columns``.
        """
        return {
            header: _to_jsonable(row[index])
            for index, (header, _) in enumerate(self.columns)
        }


# --- Per-user-scoped statement builders -------------------------------------
#
# Each returns a Select already filtered to a single user. Child tables (no
# user_id column) scope via a subquery of the parent rows the user owns — the
# isolation guarantee for Sets and route points.


def _sessions_stmt(user_id: int) -> Select:
    return select(TrainingSession).where(TrainingSession.user_id == user_id)


def _sets_stmt(user_id: int) -> Select:
    owned_sessions = select(TrainingSession.id).where(
        TrainingSession.user_id == user_id
    )
    return select(TrainingSet).where(TrainingSet.session_id.in_(owned_sessions))


def _workouts_stmt(user_id: int) -> Select:
    return select(Workout).where(Workout.user_id == user_id)


def _route_points_stmt(user_id: int) -> Select:
    owned_workouts = select(Workout.id).where(Workout.user_id == user_id)
    return select(WorkoutRoutePoint).where(
        WorkoutRoutePoint.workout_id.in_(owned_workouts)
    )


def _health_records_stmt(user_id: int) -> Select:
    return select(HealthRecord).where(HealthRecord.user_id == user_id)


def _category_records_stmt(user_id: int) -> Select:
    return select(CategoryRecord).where(CategoryRecord.user_id == user_id)


def _activity_summaries_stmt(user_id: int) -> Select:
    return select(ActivitySummary).where(ActivitySummary.user_id == user_id)


def _programs_stmt(user_id: int) -> Select:
    return select(Program).where(Program.user_id == user_id)


def _program_days_stmt(user_id: int) -> Select:
    owned_programs = select(Program.id).where(Program.user_id == user_id)
    return select(ProgramDay).where(ProgramDay.program_id.in_(owned_programs))


def _program_muscle_volumes_stmt(user_id: int) -> Select:
    owned_programs = select(Program.id).where(Program.user_id == user_id)
    return select(ProgramMuscleVolume).where(
        ProgramMuscleVolume.program_id.in_(owned_programs)
    )


def _personal_records_stmt(user_id: int) -> Select:
    return select(PersonalRecord).where(PersonalRecord.user_id == user_id)


def _custom_exercises_stmt(user_id: int) -> Select:
    # ONLY the user's own custom Exercises — the shared global library
    # (user_id IS NULL) is not personal data and is never exported.
    return select(Exercise).where(Exercise.user_id == user_id)


# --- The registry ------------------------------------------------------------

RECORD_SPECS: tuple[RecordSpec, ...] = (
    RecordSpec(
        name="sessions",
        model=TrainingSession,
        columns=(
            ("id", "id"),
            ("user_id", "user_id"),
            ("started_at", "started_at"),
            ("ended_at", "ended_at"),
        ),
        stmt_for=_sessions_stmt,
        order_by=(TrainingSession.started_at, TrainingSession.id),
    ),
    RecordSpec(
        name="sets",
        model=TrainingSet,
        columns=(
            ("id", "id"),
            ("session_id", "session_id"),
            ("exercise_id", "exercise_id"),
            ("order_index", "order_index"),
            ("weight_kg", "weight_kg"),
            ("reps", "reps"),
            ("rpe", "rpe"),
            ("set_type", "set_type"),
            ("superset_group", "superset_group"),
        ),
        stmt_for=_sets_stmt,
        order_by=(TrainingSet.session_id, TrainingSet.order_index),
    ),
    RecordSpec(
        name="workouts",
        model=Workout,
        columns=(
            ("id", "id"),
            ("user_id", "user_id"),
            ("time", "time"),
            ("end_time", "end_time"),
            ("activity_type", "activity_type"),
            ("duration_sec", "duration_sec"),
            ("total_distance_m", "total_distance_m"),
            ("total_energy_kj", "total_energy_kj"),
            ("source_id", "source_id"),
            ("batch_id", "batch_id"),
            ("metadata", "metadata_"),
        ),
        stmt_for=_workouts_stmt,
        order_by=(Workout.time, Workout.id),
    ),
    RecordSpec(
        name="workout_route_points",
        model=WorkoutRoutePoint,
        columns=(
            ("workout_id", "workout_id"),
            ("time", "time"),
            ("latitude", "latitude"),
            ("longitude", "longitude"),
            ("altitude_m", "altitude_m"),
        ),
        stmt_for=_route_points_stmt,
        order_by=(WorkoutRoutePoint.workout_id, WorkoutRoutePoint.time),
    ),
    RecordSpec(
        name="health_records",
        model=HealthRecord,
        columns=(
            ("time", "time"),
            ("metric_type", "metric_type"),
            ("value", "value"),
            ("unit", "unit"),
            ("end_time", "end_time"),
            ("source_id", "source_id"),
            ("batch_id", "batch_id"),
        ),
        stmt_for=_health_records_stmt,
        order_by=(HealthRecord.metric_type, HealthRecord.time),
    ),
    RecordSpec(
        name="category_records",
        model=CategoryRecord,
        columns=(
            ("time", "time"),
            ("category_type", "category_type"),
            ("value", "value"),
            ("value_label", "value_label"),
            ("end_time", "end_time"),
            ("source_id", "source_id"),
            ("batch_id", "batch_id"),
        ),
        stmt_for=_category_records_stmt,
        order_by=(CategoryRecord.category_type, CategoryRecord.time),
    ),
    RecordSpec(
        name="activity_summaries",
        model=ActivitySummary,
        columns=(
            ("date", "date"),
            ("active_energy_burned_kj", "active_energy_burned_kj"),
            ("active_energy_goal_kj", "active_energy_goal_kj"),
            ("exercise_minutes", "exercise_minutes"),
            ("exercise_goal_minutes", "exercise_goal_minutes"),
            ("stand_hours", "stand_hours"),
            ("stand_goal_hours", "stand_goal_hours"),
            ("batch_id", "batch_id"),
        ),
        stmt_for=_activity_summaries_stmt,
        order_by=(ActivitySummary.date,),
    ),
    RecordSpec(
        name="programs",
        model=Program,
        columns=(
            ("id", "id"),
            ("name", "name"),
            ("preset_key", "preset_key"),
            ("goal", "goal"),
            ("experience", "experience"),
            ("days_per_week", "days_per_week"),
            ("session_minutes", "session_minutes"),
            ("mesocycle_weeks", "mesocycle_weeks"),
            ("total_weeks", "total_weeks"),
            ("deload_week", "deload_week"),
            ("rep_range_low", "rep_range_low"),
            ("rep_range_high", "rep_range_high"),
            ("effort_rir", "effort_rir"),
            ("status", "status"),
            ("provenance", "provenance"),
            ("created_at", "created_at"),
        ),
        stmt_for=_programs_stmt,
        order_by=(Program.created_at, Program.id),
    ),
    RecordSpec(
        name="program_days",
        model=ProgramDay,
        columns=(
            ("id", "id"),
            ("program_id", "program_id"),
            ("day_index", "day_index"),
            ("name", "name"),
            ("slots", "slots"),
        ),
        stmt_for=_program_days_stmt,
        order_by=(ProgramDay.program_id, ProgramDay.day_index),
    ),
    RecordSpec(
        name="program_muscle_volumes",
        model=ProgramMuscleVolume,
        columns=(
            ("id", "id"),
            ("program_id", "program_id"),
            ("muscle", "muscle"),
            ("week", "week"),
            ("target_sets", "target_sets"),
            ("is_deload", "is_deload"),
        ),
        stmt_for=_program_muscle_volumes_stmt,
        order_by=(
            ProgramMuscleVolume.program_id,
            ProgramMuscleVolume.week,
            ProgramMuscleVolume.muscle,
        ),
    ),
    RecordSpec(
        name="personal_records",
        model=PersonalRecord,
        columns=(
            ("id", "id"),
            ("exercise_id", "exercise_id"),
            ("kind", "kind"),
            ("weight_bucket", "weight_bucket"),
            ("value", "value"),
            ("achieved_set_id", "achieved_set_id"),
            ("achieved_at", "achieved_at"),
        ),
        stmt_for=_personal_records_stmt,
        order_by=(PersonalRecord.exercise_id, PersonalRecord.kind),
    ),
    RecordSpec(
        name="custom_exercises",
        model=Exercise,
        columns=(
            ("id", "id"),
            ("slug", "slug"),
            ("name", "name"),
            ("category", "category"),
            ("force", "force"),
            ("level", "level"),
            ("mechanic", "mechanic"),
            ("equipment", "equipment"),
            ("instructions", "instructions"),
            ("images", "images"),
            ("source", "source"),
        ),
        stmt_for=_custom_exercises_stmt,
        order_by=(Exercise.name, Exercise.id),
    ),
)

_SPECS_BY_NAME = {spec.name: spec for spec in RECORD_SPECS}


def spec_by_name(name: str) -> RecordSpec:
    """Look up a record spec by its archive name (raises KeyError if unknown)."""
    return _SPECS_BY_NAME[name]


# --- Streaming primitives ----------------------------------------------------


async def iter_record_chunks(
    session: AsyncSession,
    spec: RecordSpec,
    user_id: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> AsyncIterator[list[dict[str, Any]]]:
    """Yield this record type's rows in bounded chunks, as JSON-able dicts.

    Goes through a **server-side cursor** (``session.stream(...).partitions``) so
    the whole table is never materialized. Each yielded chunk is at most
    ``chunk_size`` projected dicts. The query is the spec's user-scoped statement
    — isolation is enforced here, at the source.
    """
    # Project explicit columns (NOT the whole entity): a server-side cursor over
    # a full ORM entity returns JSONB columns as Python-repr strings, corrupting
    # the archive; selecting the columns applies their result processors so JSONB
    # deserializes to dict/list. The user-scoped WHERE from stmt_for is preserved.
    stmt = spec.stmt_for(user_id).with_only_columns(*spec.column_exprs)
    if spec.order_by:
        stmt = stmt.order_by(*spec.order_by)
    result = await session.stream(stmt)
    async for partition in result.partitions(chunk_size):
        yield [spec.row_to_dict(row) for row in partition]


async def _gym_profile_dict(
    session: AsyncSession, user_id: int
) -> dict[str, Any] | None:
    """The user's Gym Profile as a dict, or None if they have none.

    Read-only: unlike the API's get-or-create, the Export reports reality — a user
    who never opened Settings has no Gym Profile, and we export ``null`` rather
    than fabricating the defaults.
    """
    profile = (
        await session.execute(
            select(GymProfile).where(GymProfile.user_id == user_id)
        )
    ).scalar_one_or_none()
    if profile is None:
        return None
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "bar_weights_kg": profile.bar_weights_kg,
        "plate_weights_kg": profile.plate_weights_kg,
        "equipment": profile.equipment,
    }


# Optional nutrition record types (ADR-0006: Diary Entries). Built in #21; the
# Export includes them when the table exists and still skips gracefully when it
# doesn't (e.g. a pre-#21 schema, or the export's own test fixtures). Declared as
# (archive_name, table_name) and streamed via runtime reflection so the engine
# needn't import a model that may be absent.
_OPTIONAL_TABLES: tuple[tuple[str, str], ...] = (
    ("diary_entries", "diary_entries"),
    # Recipes (#22) — user-defined Foods composed of other Foods. The ``recipes``
    # table carries ``user_id`` so the reflection path scopes it per-user and it
    # round-trips cleanly. (``recipe_ingredients`` has no ``user_id`` — it belongs
    # to a Recipe, not directly a user — so it is NOT reflected here; a future
    # slice can join it through the owned ``recipes`` rows if needed. The Recipe's
    # computed macros also live on its backing Food, which is captured if/when the
    # custom-Food export is added.)
    ("recipes", "recipes"),
)


async def _present_optional_tables(session: AsyncSession) -> list[tuple[str, str]]:
    """Which optional (nutrition) tables actually exist in the live schema."""
    def _probe(sync_conn: Any) -> list[tuple[str, str]]:
        inspector = inspect(sync_conn)
        existing = set(inspector.get_table_names())
        return [
            (archive_name, table)
            for archive_name, table in _OPTIONAL_TABLES
            if table in existing
        ]

    conn = await session.connection()
    return await conn.run_sync(_probe)


# --- The archive builder -----------------------------------------------------


def _gym_profile_csv(profile: dict[str, Any] | None) -> str:
    """The gym_profile CSV: a header always, plus the single row if present."""
    headers = ["id", "user_id", "bar_weights_kg", "plate_weights_kg", "equipment"]
    lines = [",".join(headers)]
    if profile is not None:
        lines.append(
            ",".join(_quote_csv(_csv_cell(profile[h])) for h in headers)
        )
    return "\r\n".join(lines) + "\r\n"


def _quote_csv(cell: str) -> str:
    """Minimal RFC-4180 quoting for a single cell."""
    if any(c in cell for c in (",", '"', "\n", "\r")):
        return '"' + cell.replace('"', '""') + '"'
    return cell


def _csv_line(values: list[str]) -> str:
    return ",".join(_quote_csv(v) for v in values) + "\r\n"


async def _build_zip_to_path(
    session: AsyncSession,
    user: User,
    path: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> None:
    """Assemble the full archive ZIP onto disk at ``path``.

    Memory stays bounded: each record type is streamed through a server-side
    cursor one chunk at a time, the CSVs are written into the ZIP incrementally,
    and the JSON document is written incrementally too (arrays opened, rows
    streamed comma-separated, arrays closed) — no table is ever held whole.
    """
    generated_at = datetime.now(timezone.utc).isoformat()
    gym_profile = await _gym_profile_dict(session, user.id)
    optional = await _present_optional_tables(session)

    with ZipFile(path, "w", compression=ZIP_DEFLATED) as zf:
        # --- The JSON document, written incrementally via an open stream. ----
        with zf.open("export.json", "w") as raw_json:
            def w(text: str) -> None:
                raw_json.write(text.encode("utf-8"))

            user_obj = {
                "id": user.id,
                "email": user.email,
                "created_at": _to_jsonable(user.created_at),
            }
            w('{"user":')
            w(json.dumps(user_obj))
            w(',"generated_at":')
            w(json.dumps(generated_at))
            w(',"records":{')

            first_collection = True
            for spec in RECORD_SPECS:
                if not first_collection:
                    w(",")
                first_collection = False
                w(json.dumps(spec.name))
                w(":[")
                first_row = True
                async for chunk in iter_record_chunks(
                    session, spec, user.id, chunk_size
                ):
                    for row in chunk:
                        if not first_row:
                            w(",")
                        first_row = False
                        w(json.dumps(row))
                w("]")

            # gym_profile: a single object or null (not an array).
            w(',"gym_profile":')
            w(json.dumps(gym_profile))

            # Optional nutrition collections (only if their tables exist).
            for archive_name, table in optional:
                w(",")
                w(json.dumps(archive_name))
                w(":[")
                first_row = True
                async for chunk in _iter_table_chunks(
                    session, table, user.id, chunk_size
                ):
                    for row in chunk:
                        if not first_row:
                            w(",")
                        first_row = False
                        w(json.dumps(row))
                w("]")

            w("}}")

        # --- One CSV per record type. ----------------------------------------
        for spec in RECORD_SPECS:
            with zf.open(f"csv/{spec.name}.csv", "w") as raw_csv:
                raw_csv.write(_csv_line(spec.headers).encode("utf-8"))
                async for chunk in iter_record_chunks(
                    session, spec, user.id, chunk_size
                ):
                    if not chunk:
                        continue
                    buf = "".join(
                        _csv_line([_csv_cell(row[h]) for h in spec.headers])
                        for row in chunk
                    )
                    raw_csv.write(buf.encode("utf-8"))

        # gym_profile.csv — header always, the one row if present.
        with zf.open("csv/gym_profile.csv", "w") as raw_csv:
            raw_csv.write(_gym_profile_csv(gym_profile).encode("utf-8"))

        # Optional nutrition CSVs (only when the table exists).
        for archive_name, table in optional:
            cols = await _table_columns(session, table)
            with zf.open(f"csv/{archive_name}.csv", "w") as raw_csv:
                raw_csv.write(_csv_line(cols).encode("utf-8"))
                async for chunk in _iter_table_chunks(
                    session, table, user.id, chunk_size
                ):
                    if not chunk:
                        continue
                    buf = "".join(
                        _csv_line([_csv_cell(row[c]) for c in cols])
                        for row in chunk
                    )
                    raw_csv.write(buf.encode("utf-8"))


async def _table_columns(session: AsyncSession, table: str) -> list[str]:
    """Column names of an optional table, in declared order (introspected)."""
    def _probe(sync_conn: Any) -> list[str]:
        inspector = inspect(sync_conn)
        return [c["name"] for c in inspector.get_columns(table)]

    conn = await session.connection()
    return await conn.run_sync(_probe)


async def _iter_table_chunks(
    session: AsyncSession,
    table: str,
    user_id: int,
    chunk_size: int,
) -> AsyncIterator[list[dict[str, Any]]]:
    """Stream a per-user-scoped optional table by reflecting it at runtime.

    Used for nutrition tables that may not have an imported model yet. Assumes a
    ``user_id`` column (the platform's per-user convention); a future Diary Entry
    table is keyed that way. Streamed via a server-side cursor like the rest.
    """
    from sqlalchemy import MetaData, Table

    def _reflect(sync_conn: Any) -> Table:
        md = MetaData()
        return Table(table, md, autoload_with=sync_conn)

    conn = await session.connection()
    reflected = await conn.run_sync(_reflect)
    cols = [c.name for c in reflected.columns]
    stmt = select(reflected)
    if "user_id" in cols:
        stmt = stmt.where(reflected.c.user_id == user_id)
    result = await session.stream(stmt)
    async for partition in result.partitions(chunk_size):
        yield [
            {col: _to_jsonable(getattr(row, col)) for col in cols}
            for row in partition
        ]


def archive_filename(user: User) -> str:
    """A stable, mobile-friendly download name for a user's archive."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    local = user.email.split("@", 1)[0] if user.email else f"user{user.id}"
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in local)
    return f"health-export-{safe}-{stamp}.zip"


async def stream_export_zip(
    session: AsyncSession,
    user: User,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> AsyncIterator[bytes]:
    """Build the archive to a temp file, stream it back in chunks, then delete.

    The ZIP is assembled on disk (bounded memory; see ``_build_zip_to_path``) and
    streamed to the client in ``_FILE_READ_CHUNK`` byte slices. The temp file is
    always removed, even on a streaming error.
    """
    fd, tmp_path = tempfile.mkstemp(prefix="health-export-", suffix=".zip")
    os.close(fd)
    try:
        await _build_zip_to_path(session, user, tmp_path, chunk_size)
        with open(tmp_path, "rb") as fh:
            while True:
                chunk = fh.read(_FILE_READ_CHUNK)
                if not chunk:
                    break
                yield chunk
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
