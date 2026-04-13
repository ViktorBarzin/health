from datetime import datetime, timezone

from app.api.metrics import _apply_trend, _build_stats
from app.schemas.metrics import MetricDataPoint


def test_build_stats_returns_expected_totals() -> None:
    stats = _build_stats([2.0, 4.0, 6.0])

    assert stats.avg == 4.0
    assert stats.min == 2.0
    assert stats.max == 6.0
    assert stats.total == 12.0
    assert stats.count == 3


def test_apply_trend_compares_halves() -> None:
    data = [
        MetricDataPoint(time=datetime(2024, 1, 1, tzinfo=timezone.utc), value=10.0),
        MetricDataPoint(time=datetime(2024, 1, 2, tzinfo=timezone.utc), value=10.0),
        MetricDataPoint(time=datetime(2024, 1, 3, tzinfo=timezone.utc), value=20.0),
        MetricDataPoint(time=datetime(2024, 1, 4, tzinfo=timezone.utc), value=20.0),
    ]

    stats = _apply_trend(_build_stats([point.value for point in data]), data)

    assert stats.trend_pct == 100.0
