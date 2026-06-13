"""Principles knowledge base API — the cited exercise-science rules (#12).

A read-only browse/lookup surface over the versioned Principles KB (ADR-0004).
The deterministic Program generator (#13) calls the query *service* directly;
this HTTP layer serves the receipts UI (#14) and a browsable catalog:

* ``GET /api/principles`` — list the KB (optionally one category, or scoped to a
  ``(goal, experience)`` context the generator would see).
* ``GET /api/principles/categories`` — the category dimension, for filters.
* ``GET /api/principles/{key}`` — one Principle by its stable key ("why this
  number" deep-link), 404 if unknown.

Rules are global/shared content (not per-user), but every endpoint still requires
auth like the rest of the API. Global rows are managed by the seed
(:mod:`app.services.seed_principles`), so there are no write endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.principle import (
    ExperienceLevel,
    PrincipleCategory,
    TrainingGoal,
)
from app.models.user import User
from app.schemas.principles import CategoryOption, PrincipleRead
from app.services.principles_query import (
    applicable_principles,
    list_principles,
    principle_by_key,
)

router = APIRouter()


@router.get("/", response_model=list[PrincipleRead])
async def list_principles_endpoint(
    goal: TrainingGoal | None = Query(default=None),
    experience: ExperienceLevel | None = Query(default=None),
    category: PrincipleCategory | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PrincipleRead]:
    """Browse the KB; scope to a ``(goal, experience)`` context when given.

    With neither ``goal`` nor ``experience`` it returns the whole catalog (the
    browse view); with either, it returns exactly the Principles that apply to
    that context — the same set #13's generator composes from — so the receipts UI
    can show "the rules behind your Program". ``category`` narrows either view.
    """
    if goal is not None or experience is not None:
        principles = await applicable_principles(
            db, goal=goal, experience=experience, category=category
        )
    else:
        principles = await list_principles(db, category=category)
    return [PrincipleRead.model_validate(p) for p in principles]


@router.get("/categories", response_model=list[CategoryOption])
async def list_categories(
    user: User = Depends(get_current_user),
) -> list[CategoryOption]:
    """The typed category dimension, for filter dropdowns."""
    return [
        CategoryOption(value=c.value, label=c.value.replace("_", " ").title())
        for c in PrincipleCategory
    ]


@router.get("/{key}", response_model=PrincipleRead)
async def get_principle(
    key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PrincipleRead:
    """Fetch one Principle by its stable key (the "why this number" deep-link)."""
    principle = await principle_by_key(db, key)
    if principle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Principle not found"
        )
    return PrincipleRead.model_validate(principle)
