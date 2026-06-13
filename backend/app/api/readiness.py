"""Readiness API — the daily biometric signal (#14, ADR-0004).

A single per-user, read-only endpoint over the pure Readiness core
(:mod:`app.services.readiness`) and its query glue
(:mod:`app.services.readiness_query`):

* ``GET /api/readiness`` — today's 0–100 Readiness score, its band, and the
  per-metric components (recent vs the user's own baseline) for the "why this
  number" explainer. Returns an ``insufficient_data`` result (null score) when
  the user has no usable HRV / resting-HR / sleep history, never a fabricated
  number.

Readiness is computed from the user's own health metrics (Apple Health, etc.),
so it is per-user and scoped to ``get_current_user``. It is distinct from
training-load **Recovery** (#10), which the analytics API serves.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.readiness import ReadinessComponentRead, ReadinessResponse
from app.services.readiness_query import readiness_for_user

router = APIRouter()


@router.get("", response_model=ReadinessResponse)
async def get_readiness(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReadinessResponse:
    """Today's Readiness signal for the caller, with its per-metric breakdown."""
    now = datetime.now(timezone.utc)
    readiness = await readiness_for_user(db, user.id, now=now)
    return ReadinessResponse(
        score=readiness.score,
        band=readiness.band,
        insufficient_data=readiness.insufficient_data,
        components=[
            ReadinessComponentRead(
                metric=c.metric,
                recent=c.recent,
                baseline=c.baseline,
                score=c.score,
                weight=c.weight,
                direction=c.direction,
            )
            for c in readiness.components
        ],
    )
