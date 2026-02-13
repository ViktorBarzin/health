"""Unit tests for XML parser helper functions."""

import uuid
from datetime import datetime, timezone

import pytest
from lxml import etree

from app.services.xml_parser import (
    _clean_type_name,
    _convert_to_kj,
    _parse_apple_date,
    _process_record_element,
    _safe_float,
    _safe_int,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_record_element(
    type_str: str,
    value: str,
    start_date: str,
    unit: str = "count",
    end_date: str | None = None,
) -> etree._Element:
    """Create a mock <Record> XML element."""
    attrs = {
        "type": type_str,
        "value": value,
        "startDate": start_date,
        "unit": unit,
    }
    if end_date:
        attrs["endDate"] = end_date
    return etree.Element("Record", **attrs)


# ---------------------------------------------------------------------------
# _parse_apple_date
# ---------------------------------------------------------------------------


class TestParseAppleDate:
    def test_valid_date_string(self):
        result = _parse_apple_date("2024-01-15 08:30:00 -0500")
        assert result is not None
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 8
        assert result.minute == 30

    def test_none_returns_none(self):
        assert _parse_apple_date(None) is None

    def test_invalid_string_returns_none(self):
        assert _parse_apple_date("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert _parse_apple_date("") is None


# ---------------------------------------------------------------------------
# _clean_type_name
# ---------------------------------------------------------------------------


class TestCleanTypeName:
    def test_strips_prefix(self):
        result = _clean_type_name(
            "HKQuantityTypeIdentifierStepCount",
            "HKQuantityTypeIdentifier",
        )
        assert result == "StepCount"

    def test_without_prefix_returns_original(self):
        result = _clean_type_name("CustomMetric", "HKQuantityTypeIdentifier")
        assert result == "CustomMetric"


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------


class TestSafeFloat:
    def test_valid_string(self):
        assert _safe_float("3.14") == 3.14

    def test_none_returns_none(self):
        assert _safe_float(None) is None

    def test_invalid_string_returns_none(self):
        assert _safe_float("not-a-number") is None

    def test_integer_string(self):
        assert _safe_float("42") == 42.0


# ---------------------------------------------------------------------------
# _safe_int
# ---------------------------------------------------------------------------


class TestSafeInt:
    def test_valid_string(self):
        assert _safe_int("42") == 42

    def test_none_returns_none(self):
        assert _safe_int(None) is None

    def test_invalid_string_returns_none(self):
        assert _safe_int("not-a-number") is None

    def test_float_string_returns_none(self):
        # int("3.14") raises ValueError
        assert _safe_int("3.14") is None


# ---------------------------------------------------------------------------
# _convert_to_kj
# ---------------------------------------------------------------------------


class TestConvertToKj:
    def test_kcal_conversion(self):
        result = _convert_to_kj(100.0, "kcal")
        assert result is not None
        assert abs(result - 418.4) < 0.01

    def test_kj_passthrough(self):
        result = _convert_to_kj(500.0, "kJ")
        assert result == 500.0

    def test_none_value_returns_none(self):
        assert _convert_to_kj(None, "kcal") is None

    def test_none_unit_returns_none(self):
        assert _convert_to_kj(100.0, None) is None


# ---------------------------------------------------------------------------
# _process_record_element
# ---------------------------------------------------------------------------

_TEST_USER_ID = 1
_TEST_BATCH_ID = str(uuid.uuid4())
_TEST_SOURCE_ID = 1


class TestProcessRecordElement:
    def test_valid_health_record(self):
        elem = make_record_element(
            type_str="HKQuantityTypeIdentifierStepCount",
            value="1234",
            start_date="2024-01-15 08:00:00 -0500",
            unit="count",
        )
        result = _process_record_element(
            elem, _TEST_USER_ID, _TEST_BATCH_ID, _TEST_SOURCE_ID
        )
        assert result is not None
        kind, data = result
        assert kind == "health"
        assert data["metric_type"] == "StepCount"
        assert data["value"] == 1234.0
        assert data["unit"] == "count"
        assert data["user_id"] == _TEST_USER_ID

    def test_valid_category_record(self):
        elem = make_record_element(
            type_str="HKCategoryTypeIdentifierSleepAnalysis",
            value="HKCategoryValueSleepAnalysisAsleepDeep",
            start_date="2024-01-15 23:00:00 -0500",
        )
        result = _process_record_element(
            elem, _TEST_USER_ID, _TEST_BATCH_ID, _TEST_SOURCE_ID
        )
        assert result is not None
        kind, data = result
        assert kind == "category"
        assert data["category_type"] == "SleepAnalysis"
        assert data["user_id"] == _TEST_USER_ID

    def test_missing_start_date_returns_none(self):
        # Create element without startDate attribute
        elem = etree.Element(
            "Record",
            type="HKQuantityTypeIdentifierStepCount",
            value="100",
            unit="count",
        )
        result = _process_record_element(
            elem, _TEST_USER_ID, _TEST_BATCH_ID, _TEST_SOURCE_ID
        )
        assert result is None

    def test_missing_value_returns_none(self):
        """A quantity record without a parseable numeric value returns None."""
        elem = etree.Element(
            "Record",
            type="HKQuantityTypeIdentifierStepCount",
            startDate="2024-01-15 08:00:00 -0500",
            unit="count",
            # value attribute is missing
        )
        result = _process_record_element(
            elem, _TEST_USER_ID, _TEST_BATCH_ID, _TEST_SOURCE_ID
        )
        assert result is None
