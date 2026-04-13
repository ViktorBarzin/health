from pathlib import Path

from lxml import etree

from app.services.xml_parser import (
    _process_activity_summary_element,
    _process_record_element,
    _process_workout_element,
)


def test_process_record_element_category_uses_clean_labels() -> None:
    elem = etree.fromstring(
        """
        <Record
            type="HKCategoryTypeIdentifierSleepAnalysis"
            sourceName="Watch"
            startDate="2024-01-01 23:00:00 +0000"
            endDate="2024-01-02 07:00:00 +0000"
            value="HKCategoryValueSleepAnalysisAsleepREM"
        />
        """
    )

    result = _process_record_element(elem, user_id=1, batch_id="batch", source_id=2)

    assert result is not None
    kind, record = result
    assert kind == "category"
    assert record["category_type"] == "SleepAnalysis"
    assert record["value_label"] == "Sleep Analysis Asleep REM"


def test_process_activity_summary_includes_batch_id() -> None:
    elem = etree.fromstring(
        """
        <ActivitySummary
            dateComponents="2024-01-02"
            activeEnergyBurned="320"
            activeEnergyBurnedUnit="kcal"
            activeEnergyBurnedGoal="500"
            appleExerciseTime="45"
            appleExerciseTimeGoal="30"
            appleStandHours="10"
            appleStandHoursGoal="12"
        />
        """
    )

    summary = _process_activity_summary_element(elem, user_id=1, batch_id="batch-123")

    assert summary is not None
    assert summary["batch_id"] == "batch-123"
    assert summary["exercise_minutes"] == 45.0
    assert summary["stand_hours"] == 10


def test_process_workout_element_loads_route_points_from_gpx(tmp_path: Path) -> None:
    route_dir = tmp_path / "workout-routes"
    route_dir.mkdir()
    route_path = route_dir / "sample-route.gpx"
    route_path.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" creator="pytest" xmlns="http://www.topografix.com/GPX/1/1">
          <trk><trkseg>
            <trkpt lat="51.5000" lon="-0.1200"><ele>10.5</ele><time>2024-01-01T10:00:00Z</time></trkpt>
            <trkpt lat="51.5005" lon="-0.1205"><ele>11.0</ele><time>2024-01-01T10:01:00Z</time></trkpt>
          </trkseg></trk>
        </gpx>
        """,
        encoding="utf-8",
    )

    elem = etree.fromstring(
        """
        <Workout
            workoutActivityType="HKWorkoutActivityTypeRunning"
            duration="30"
            durationUnit="min"
            totalDistance="5"
            totalDistanceUnit="km"
            totalEnergyBurned="350"
            totalEnergyBurnedUnit="kcal"
            startDate="2024-01-01 10:00:00 +0000"
            endDate="2024-01-01 10:30:00 +0000"
        >
            <WorkoutRoute>
                <FileReference path="workout-routes/sample-route.gpx" />
            </WorkoutRoute>
        </Workout>
        """
    )

    workout, route_points = _process_workout_element(
        elem,
        user_id=1,
        batch_id="batch",
        source_id=2,
        route_base_dir=tmp_path,
    )

    assert workout["activity_type"] == "Running"
    assert workout["duration_sec"] == 1800.0
    assert workout["total_distance_m"] == 5000.0
    assert len(route_points) == 2
    assert route_points[0]["latitude"] == 51.5
    assert route_points[0]["longitude"] == -0.12
