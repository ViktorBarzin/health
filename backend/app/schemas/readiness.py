"""Pydantic schemas for the Readiness endpoint (#14, ADR-0004).

A **Readiness** is the daily biometric 0–100 signal derived from HRV, resting
heart rate, and sleep trends (CONTEXT.md). The wire shape exposes the score, its
band label, and the per-metric **components** (recent vs the user's baseline) so
the dashboard insight can show "why this number" — e.g. "HRV below your
baseline". An ``insufficient_data`` result carries a null score honestly rather
than a fabricated number.
"""

from __future__ import annotations

from pydantic import BaseModel


class ReadinessComponentRead(BaseModel):
    """One metric's contribution to the Readiness score (for the explainer)."""

    metric: str
    recent: float
    baseline: float
    score: float
    weight: float
    direction: str


class ReadinessResponse(BaseModel):
    """Today's Readiness signal: the 0–100 score, its band, and its components.

    ``insufficient_data`` is true (and ``score``/``band`` null) when the user has
    no usable biometric history — the UI then prompts them to connect a data
    source rather than showing a misleading number.
    """

    score: float | None = None
    band: str | None = None
    insufficient_data: bool = False
    components: list[ReadinessComponentRead] = []
