"""Pure Fitbod-CSV parser: column-name parsing, units, warmups, grouping, skips.

These exercise the rules in :mod:`app.services.fitbod_parser` without a DB — the
parser is pure, so the column-name robustness, kg/lb conversion, warmup→set_type
mapping, Session grouping and non-strength-row skipping are all asserted here.
"""

from datetime import timezone

import pytest

from app.services.fitbod_parser import (
    FitbodParseError,
    parse_fitbod_csv,
)

# The real Fitbod export header (verified against real-export parsers).
HEADER = (
    "Date,Exercise,Reps,Weight(kg),Duration(s),Distance(m),"
    "Incline,Resistance,isWarmup,Note,multiplier"
)


def _csv(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


# --------------------------------------------------------------------------- #
# Happy path: one workout → one Session with ordered Sets
# --------------------------------------------------------------------------- #


def test_single_workout_groups_into_one_session() -> None:
    text = _csv(
        "2021-12-27 10:02:51 +0000,Back Squat,5,100.0,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-27 10:02:51 +0000,Back Squat,5,102.5,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-27 10:02:51 +0000,Bench Press,8,80.0,0.0,0.0,0.0,0.0,false,,1.0",
    )
    result = parse_fitbod_csv(text)

    assert len(result.sessions) == 1
    session = result.sessions[0]
    assert session.started_at.year == 2021
    assert session.started_at.month == 12
    assert session.started_at.day == 27
    assert session.started_at.utcoffset().total_seconds() == 0
    assert len(session.sets) == 3
    # Set fields parsed and converted.
    assert session.sets[0].exercise_name == "Back Squat"
    assert session.sets[0].weight_kg == 100.0
    assert session.sets[0].reps == 5
    assert session.sets[0].is_warmup is False


def test_sets_keep_csv_order_via_zero_based_order_index() -> None:
    text = _csv(
        "2021-12-27 10:02:51 +0000,Back Squat,5,100.0,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-27 10:02:51 +0000,Bench Press,8,80.0,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-27 10:02:51 +0000,Deadlift,3,140.0,0.0,0.0,0.0,0.0,false,,1.0",
    )
    session = parse_fitbod_csv(text).sessions[0]
    assert [s.order_index for s in session.sets] == [0, 1, 2]
    assert [s.exercise_name for s in session.sets] == [
        "Back Squat",
        "Bench Press",
        "Deadlift",
    ]


def test_distinct_timestamps_become_distinct_sessions_in_order() -> None:
    text = _csv(
        "2021-12-25 09:00:00 +0000,Back Squat,5,100.0,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-27 10:00:00 +0000,Bench Press,8,80.0,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-25 09:00:00 +0000,Bench Press,8,80.0,0.0,0.0,0.0,0.0,false,,1.0",
    )
    result = parse_fitbod_csv(text)
    assert len(result.sessions) == 2
    # First-seen order preserved: the 25th's group came first.
    assert result.sessions[0].started_at.day == 25
    assert len(result.sessions[0].sets) == 2  # both 25th rows grouped together
    assert result.sessions[1].started_at.day == 27
    assert len(result.sessions[1].sets) == 1


# --------------------------------------------------------------------------- #
# Warmup flag → set type
# --------------------------------------------------------------------------- #


def test_warmup_flag_true_marks_set_as_warmup() -> None:
    text = _csv(
        "2021-12-27 10:02:51 +0000,Back Squat,5,60.0,0.0,0.0,0.0,0.0,true,,1.0",
        "2021-12-27 10:02:51 +0000,Back Squat,5,100.0,0.0,0.0,0.0,0.0,false,,1.0",
    )
    session = parse_fitbod_csv(text).sessions[0]
    assert session.sets[0].is_warmup is True
    assert session.sets[1].is_warmup is False


def test_blank_warmup_cell_is_not_a_warmup() -> None:
    text = _csv(
        "2021-12-27 10:02:51 +0000,Back Squat,5,100.0,0.0,0.0,0.0,0.0,,,1.0",
    )
    session = parse_fitbod_csv(text).sessions[0]
    assert session.sets[0].is_warmup is False


# --------------------------------------------------------------------------- #
# Unit detection: the unit lives in the weight column header
# --------------------------------------------------------------------------- #


def test_pounds_header_converts_weight_to_kg() -> None:
    header = (
        "Date,Exercise,Reps,Weight(lbs),Duration(s),Distance(m),"
        "Incline,Resistance,isWarmup,Note,multiplier"
    )
    text = (
        header
        + "\n2021-12-27 10:02:51 +0000,Bench Press,5,225.0,0.0,0.0,0.0,0.0,false,,1.0\n"
    )
    session = parse_fitbod_csv(text).sessions[0]
    # 225 lb ≈ 102.058 kg
    assert session.sets[0].weight_kg == pytest.approx(102.058, abs=0.01)


def test_lb_singular_header_also_recognised_as_pounds() -> None:
    header = "Date,Exercise,Reps,Weight(lb),isWarmup"
    text = header + "\n2021-12-27 10:02:51 +0000,Curl,10,45.0,false\n"
    session = parse_fitbod_csv(text).sessions[0]
    assert session.sets[0].weight_kg == pytest.approx(20.41, abs=0.01)


def test_kg_header_is_not_converted() -> None:
    text = _csv(
        "2021-12-27 10:02:51 +0000,Bench Press,5,100.0,0.0,0.0,0.0,0.0,false,,1.0",
    )
    session = parse_fitbod_csv(text).sessions[0]
    assert session.sets[0].weight_kg == 100.0


def test_unmarked_weight_header_assumed_kg() -> None:
    header = "Date,Exercise,Reps,Weight,isWarmup"
    text = header + "\n2021-12-27 10:02:51 +0000,Bench Press,5,100.0,false\n"
    session = parse_fitbod_csv(text).sessions[0]
    assert session.sets[0].weight_kg == 100.0


# --------------------------------------------------------------------------- #
# Column-name robustness: order/extra/missing columns, case
# --------------------------------------------------------------------------- #


def test_columns_parsed_by_name_not_position() -> None:
    # Reordered + an unexpected extra column. Names still resolve.
    header = "Note,Exercise,Weight(kg),Reps,isWarmup,Date,SomeFutureColumn"
    text = (
        header
        + "\nGreat set,Back Squat,100.0,5,false,2021-12-27 10:02:51 +0000,xyz\n"
    )
    session = parse_fitbod_csv(text).sessions[0]
    assert session.sets[0].exercise_name == "Back Squat"
    assert session.sets[0].weight_kg == 100.0
    assert session.sets[0].reps == 5


def test_header_matching_is_case_insensitive_and_trims() -> None:
    header = " DATE , Exercise , REPS , Weight(KG) , IsWarmup "
    text = header + "\n2021-12-27 10:02:51 +0000,Curl,10,30.0,FALSE\n"
    session = parse_fitbod_csv(text).sessions[0]
    assert session.sets[0].exercise_name == "Curl"
    assert session.sets[0].reps == 10
    assert session.sets[0].is_warmup is False


def test_missing_required_headers_raises() -> None:
    # No Reps column at all → not a Fitbod export.
    header = "Date,Exercise,Weight(kg)"
    text = header + "\n2021-12-27 10:02:51 +0000,Back Squat,100.0\n"
    with pytest.raises(FitbodParseError):
        parse_fitbod_csv(text)


def test_empty_file_raises() -> None:
    with pytest.raises(FitbodParseError):
        parse_fitbod_csv("")


# --------------------------------------------------------------------------- #
# Quoting / blank / messy rows
# --------------------------------------------------------------------------- #


def test_quoted_fields_with_embedded_commas() -> None:
    text = _csv(
        '2021-12-27 10:02:51 +0000,"Squat, Barbell",5,100.0,0.0,0.0,0.0,0.0,false,"felt heavy, deep",1.0',
    )
    session = parse_fitbod_csv(text).sessions[0]
    assert session.sets[0].exercise_name == "Squat, Barbell"
    assert session.sets[0].weight_kg == 100.0


def test_blank_lines_between_rows_are_ignored() -> None:
    text = (
        HEADER
        + "\n2021-12-27 10:02:51 +0000,Back Squat,5,100.0,0.0,0.0,0.0,0.0,false,,1.0"
        + "\n\n"  # stray blank line
        + "\n2021-12-27 10:02:51 +0000,Bench Press,8,80.0,0.0,0.0,0.0,0.0,false,,1.0\n"
    )
    result = parse_fitbod_csv(text)
    assert result.set_count == 2


# --------------------------------------------------------------------------- #
# Non-strength rows are skipped, not turned into garbage Sets
# --------------------------------------------------------------------------- #


def test_cardio_distance_row_is_skipped() -> None:
    # A treadmill run: no weight, no reps, but Duration + Distance present.
    text = _csv(
        "2021-12-27 10:02:51 +0000,Back Squat,5,100.0,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-27 10:30:00 +0000,Running,0,0.0,1800.0,5000.0,0.0,0.0,false,,1.0",
    )
    result = parse_fitbod_csv(text)
    assert result.set_count == 1  # only the squat
    assert result.skipped_rows == 1
    assert result.sessions[0].sets[0].exercise_name == "Back Squat"


def test_bodyweight_set_zero_weight_positive_reps_is_kept() -> None:
    # Pull-ups: weight 0 but reps > 0 — a real strength Set.
    text = _csv(
        "2021-12-27 10:02:51 +0000,Pull Up,12,0.0,0.0,0.0,0.0,0.0,false,,1.0",
    )
    result = parse_fitbod_csv(text)
    assert result.set_count == 1
    assert result.skipped_rows == 0
    assert result.sessions[0].sets[0].weight_kg == 0.0
    assert result.sessions[0].sets[0].reps == 12


def test_row_with_no_date_is_skipped() -> None:
    text = _csv(
        ",Back Squat,5,100.0,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-27 10:02:51 +0000,Bench Press,8,80.0,0.0,0.0,0.0,0.0,false,,1.0",
    )
    result = parse_fitbod_csv(text)
    assert result.set_count == 1
    assert result.skipped_rows == 1


def test_date_without_timezone_is_parsed() -> None:
    text = _csv(
        "2021-12-27 10:02:51,Back Squat,5,100.0,0.0,0.0,0.0,0.0,false,,1.0",
    )
    result = parse_fitbod_csv(text)
    assert result.set_count == 1
    assert result.sessions[0].started_at.year == 2021


def test_exercise_names_aggregated_and_sorted() -> None:
    text = _csv(
        "2021-12-27 10:02:51 +0000,Back Squat,5,100.0,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-27 10:02:51 +0000,Bench Press,8,80.0,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-28 10:02:51 +0000,Back Squat,5,100.0,0.0,0.0,0.0,0.0,false,,1.0",
    )
    result = parse_fitbod_csv(text)
    assert result.exercise_names == ["Back Squat", "Bench Press"]


def test_set_counts_by_name_counts_kept_sets() -> None:
    text = _csv(
        "2021-12-27 10:02:51 +0000,Back Squat,5,100.0,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-27 10:02:51 +0000,Back Squat,5,102.5,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-28 10:02:51 +0000,Back Squat,5,105.0,0.0,0.0,0.0,0.0,false,,1.0",
        "2021-12-28 10:30:00 +0000,Running,0,0.0,1800.0,5000.0,0,0,false,,1.0",
    )
    counts = parse_fitbod_csv(text).set_counts_by_name()
    assert counts == {"Back Squat": 3}  # cardio "Running" row skipped, not counted
