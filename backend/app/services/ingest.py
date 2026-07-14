"""Apple Health push-ingest parsing (M7, ADR-0012) — pure, no DB.

The iOS Shortcut speaks two dialects, both parsed here into one normal form:

- **CSV lines** (Shortcut-friendly — built with Repeat + Combine Text):
    ``metric,<type>,<ISO time>,<value>[,<unit>]``
    ``sleep,<ISO start>,<ISO end>,<stage>``
    ``workout,<type>,<ISO start>,<ISO end>[,<kcal>[,<km>]]``
- **JSON**: ``{"metrics": [...], "sleep": [...], "workouts": [...]}``.

Honesty rules (the Fitbod/OFF skip-don't-fabricate lineage): a line/entry that
can't be parsed or names an unsupported type is **skipped and counted**, never
guessed at. Type spellings are normalised (Shortcut display names and
``HKQuantityTypeIdentifier…`` both map onto the canonical metric types the
rest of the app reads); pounds convert to kg; sleep stages map onto the HK
``Asleep*`` labels the Readiness ``%Asleep%`` filter matches.

Scope is the ENGINE-CRITICAL set (grill 2026-07-14): HRV, resting HR, sleep,
body mass/fat/lean, active energy, workouts. High-frequency series stay on the
occasional export.zip by design.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

#: lb → kg (the XML importer's constant, repeated here for the pure layer).
_LB_TO_KG = 0.45359237

#: Canonical metric type + unit, keyed by every accepted spelling (lowercase).
_METRIC_TYPES: dict[str, tuple[str, str]] = {}


def _register(canonical: str, unit: str, *spellings: str) -> None:
    for s in (canonical, f"HKQuantityTypeIdentifier{canonical}", *spellings):
        _METRIC_TYPES[s.lower()] = (canonical, unit)


_register(
    "HeartRateVariabilitySDNN", "ms", "Heart Rate Variability", "HRV"
)
_register("RestingHeartRate", "count/min", "Resting Heart Rate")
_register("BodyMass", "kg", "Body Mass", "Weight")
_register("BodyFatPercentage", "%", "Body Fat Percentage")
_register("LeanBodyMass", "kg", "Lean Body Mass")
_register("ActiveEnergyBurned", "kcal", "Active Energy", "Active Energy Burned")

#: Sleep stage (lowercase) → the HK category value persisted (the Readiness
#: filter matches ``%Asleep%``, so only genuine sleep carries it).
_SLEEP_STAGES: dict[str, str] = {
    "asleep": "HKCategoryValueSleepAnalysisAsleepUnspecified",
    "core": "HKCategoryValueSleepAnalysisAsleepCore",
    "deep": "HKCategoryValueSleepAnalysisAsleepDeep",
    "rem": "HKCategoryValueSleepAnalysisAsleepREM",
    "in bed": "HKCategoryValueSleepAnalysisInBed",
    "awake": "HKCategoryValueSleepAnalysisAwake",
}


@dataclass(frozen=True)
class MetricSample:
    type: str
    time: dt.datetime
    value: float
    unit: str


@dataclass(frozen=True)
class SleepInterval:
    start: dt.datetime
    end: dt.datetime
    category_value: str
    label: str


@dataclass(frozen=True)
class WorkoutSample:
    type: str
    start: dt.datetime
    end: dt.datetime
    energy_kcal: float | None
    distance_km: float | None


@dataclass
class ParsedPayload:
    metrics: list[MetricSample] = field(default_factory=list)
    sleep: list[SleepInterval] = field(default_factory=list)
    workouts: list[WorkoutSample] = field(default_factory=list)
    skipped: int = 0


def _parse_time(raw: str) -> dt.datetime | None:
    raw = raw.strip()
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _normalize_metric(
    type_raw: str, time_raw: str, value_raw: str, unit_raw: str = ""
) -> MetricSample | None:
    entry = _METRIC_TYPES.get(type_raw.strip().lower())
    time = _parse_time(time_raw)
    try:
        value = float(value_raw)
    except (TypeError, ValueError):
        return None
    if entry is None or time is None:
        return None
    canonical, unit = entry
    given_unit = (unit_raw or "").strip().lower()
    if canonical in ("BodyMass", "LeanBodyMass") and given_unit in ("lb", "lbs"):
        value *= _LB_TO_KG
    elif given_unit:
        unit = unit_raw.strip() if given_unit != unit.lower() else unit
        # Weight types always persist kg; everything else keeps the given unit.
        if canonical in ("BodyMass", "LeanBodyMass"):
            unit = "kg"
    return MetricSample(type=canonical, time=time, value=value, unit=unit)


def _normalize_sleep(start_raw: str, end_raw: str, stage_raw: str) -> SleepInterval | None:
    start = _parse_time(start_raw)
    end = _parse_time(end_raw)
    stage = stage_raw.strip()
    category = _SLEEP_STAGES.get(stage.lower())
    if start is None or end is None or category is None or end <= start:
        return None
    return SleepInterval(start=start, end=end, category_value=category, label=stage)


def _normalize_workout(
    type_raw: str,
    start_raw: str,
    end_raw: str,
    kcal_raw: str = "",
    km_raw: str = "",
) -> WorkoutSample | None:
    start = _parse_time(start_raw)
    end = _parse_time(end_raw)
    wtype = type_raw.strip()
    if start is None or end is None or not wtype or end <= start:
        return None

    def _opt(raw: str) -> float | None:
        raw = (raw or "").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    return WorkoutSample(
        type=wtype,
        start=start,
        end=end,
        energy_kcal=_opt(kcal_raw),
        distance_km=_opt(km_raw),
    )


def parse_csv(text: str) -> ParsedPayload:
    """Parse the Shortcut's line dialect (see module docstring)."""
    out = ParsedPayload()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        kind = parts[0].lower()
        parsed: object | None = None
        if kind == "metric" and len(parts) >= 4:
            parsed = _normalize_metric(*parts[1:5]) if len(parts) >= 5 else _normalize_metric(*parts[1:4])
            if parsed is not None:
                out.metrics.append(parsed)  # type: ignore[arg-type]
        elif kind == "sleep" and len(parts) >= 4:
            parsed = _normalize_sleep(parts[1], parts[2], parts[3])
            if parsed is not None:
                out.sleep.append(parsed)  # type: ignore[arg-type]
        elif kind == "workout" and len(parts) >= 4:
            parsed = _normalize_workout(*parts[1:6])
            if parsed is not None:
                out.workouts.append(parsed)  # type: ignore[arg-type]
        if parsed is None:
            out.skipped += 1
    return out


def parse_json(doc: dict) -> ParsedPayload:
    """Parse the JSON dialect (same normal form, same skip-don't-guess)."""
    out = ParsedPayload()
    for item in doc.get("metrics") or []:
        if not isinstance(item, dict):
            out.skipped += 1
            continue
        parsed = _normalize_metric(
            str(item.get("type", "")),
            str(item.get("time", "")),
            str(item.get("value", "")),
            str(item.get("unit", "") or ""),
        )
        if parsed is None:
            out.skipped += 1
        else:
            out.metrics.append(parsed)
    for item in doc.get("sleep") or []:
        if not isinstance(item, dict):
            out.skipped += 1
            continue
        parsed = _normalize_sleep(
            str(item.get("start", "")),
            str(item.get("end", "")),
            str(item.get("stage", "") or item.get("value", "")),
        )
        if parsed is None:
            out.skipped += 1
        else:
            out.sleep.append(parsed)
    for item in doc.get("workouts") or []:
        if not isinstance(item, dict):
            out.skipped += 1
            continue
        parsed = _normalize_workout(
            str(item.get("type", "")),
            str(item.get("start", "")),
            str(item.get("end", "")),
            str(item.get("energy_kcal", "") or ""),
            str(item.get("distance_km", "") or ""),
        )
        if parsed is None:
            out.skipped += 1
        else:
            out.workouts.append(parsed)
    return out
