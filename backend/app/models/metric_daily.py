"""MetricDaily — the daily per-metric rollup of ``health_records`` (ADR-0009).

The dashboard/metrics read path used to aggregate raw ``health_records`` on every
wide-window load: a ``GROUP BY date_trunc('day', time)`` over a high-volume metric
(HeartRate ≈ 1.05M rows for one prod user) scans the whole window and spills the
sort to disk (~1.6 s), and several such queries fire per load. ADR-0009 fixes that
by pre-aggregating to one row per ``(user_id, metric_type, day)`` and reading the
rollup instead — a 1M-row scan+sort becomes a ≤~1,900-row read.

One row carries everything needed to re-bucket to coarser resolutions:

* ``count`` — number of raw readings that fell in the day (Σ over a week = weekly count).
* ``sum``   — Σ of the raw values (weekly Σsum; weekly avg = Σsum / Σcount).
* ``min`` / ``max`` — daily extrema (weekly min = min(min), weekly max = max(max)).
* ``unit``  — a representative unit for the day (``max(unit)``, the same cheap pick
  the metrics-list endpoint already uses), so the read path can echo a unit without
  touching ``health_records``.

Average is **derived** (``sum / count``), never stored, so it can never drift from
the components. The ``day`` is a plain ``DATE`` (the UTC calendar day —
``date_trunc('day', time)::date`` — see :mod:`app.services.rollup`); the read helper
re-buckets it for week/month with the **same** ``date_trunc`` the raw path used, so
rollup-derived answers equal the old raw-aggregation answers exactly.

This table is **derived data**: it is rebuilt by a one-time backfill and kept fresh
by a targeted post-ingest recompute of only the buckets a batch touched (see
:mod:`app.services.rollup`). It only covers ``health_records`` — ``category_records``
(sleep, etc.) are lower-volume and stay query-time per ADR-0009.
"""

from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MetricDaily(Base):
    """One daily rollup bucket of ``health_records`` for a (user, metric)."""

    __tablename__ = "metric_daily"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    metric_type: Mapped[str] = mapped_column(String, primary_key=True)
    # The UTC calendar day the readings fall in (date_trunc('day', time)::date).
    day: Mapped[date_type] = mapped_column(Date, primary_key=True)

    # Aggregates over the raw readings in this (user, metric, day). avg is derived
    # (sum / count) and intentionally NOT stored.
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    sum: Mapped[float] = mapped_column(Float, nullable=False)
    min: Mapped[float] = mapped_column(Float, nullable=False)
    max: Mapped[float] = mapped_column(Float, nullable=False)
    # A representative unit for the day (max(unit) — the same cheap pick the
    # metrics-list endpoint uses). Nullable for safety; in practice always set.
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
