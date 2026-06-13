"""Gym Profile API — a user's available equipment.

CONTEXT.md ("Gym Profile"): the user's set of available equipment. A singleton
per user: ``GET /api/gym-profile`` get-or-creates it (returning the standard
defaults the first time, so the plate calculator works out of the box), and
``PUT /api/gym-profile`` replaces its fields. Scoped to ``get_current_user`` — a
user only ever sees or edits their own profile.

Consumed by the plate/warm-up calculators now (bar + plate denominations) and by
the freestyle Recommendation engine (#11) later (the equipment list).
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.gym_profile import (
    DEFAULT_BAR_WEIGHTS_KG,
    DEFAULT_EQUIPMENT,
    DEFAULT_PLATE_WEIGHTS_KG,
    GymProfile,
)
from app.models.user import User
from app.schemas.gym_profile import GymProfileRead, GymProfileUpdate

router = APIRouter()


async def _get_or_create_profile(db: AsyncSession, user: User) -> GymProfile:
    """Load the caller's Gym Profile, creating it with defaults if absent.

    Mirrors how ``get_current_user`` get-or-creates the User: the profile is a
    singleton the user edits, so the first read materializes it with the standard
    metric-gym defaults rather than 404ing.
    """
    profile = (
        await db.execute(
            select(GymProfile).where(GymProfile.user_id == user.id)
        )
    ).scalar_one_or_none()
    if profile is None:
        profile = GymProfile(
            user_id=user.id,
            bar_weights_kg=list(DEFAULT_BAR_WEIGHTS_KG),
            plate_weights_kg=list(DEFAULT_PLATE_WEIGHTS_KG),
            equipment=list(DEFAULT_EQUIPMENT),
        )
        db.add(profile)
        await db.flush()
    return profile


@router.get("", response_model=GymProfileRead)
async def get_gym_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GymProfileRead:
    """Get the caller's Gym Profile (created with defaults on first access)."""
    profile = await _get_or_create_profile(db, user)
    return GymProfileRead.model_validate(profile)


@router.put("", response_model=GymProfileRead)
async def update_gym_profile(
    payload: GymProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> GymProfileRead:
    """Replace the caller's Gym Profile equipment (full-object update)."""
    profile = await _get_or_create_profile(db, user)
    profile.bar_weights_kg = payload.bar_weights_kg
    profile.plate_weights_kg = payload.plate_weights_kg
    profile.equipment = payload.equipment
    await db.flush()
    return GymProfileRead.model_validate(profile)
