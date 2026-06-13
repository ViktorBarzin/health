"""Authentication API routes.

Identity comes from Authentik forward-auth (ADR-0003); the app does not run its
own login. The only endpoint is ``/me``, which returns the forward-auth user the
dependency resolved (auto-provisioning on first sight).
"""

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user
from app.models.user import User
from app.schemas.auth import UserResponse

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def me(
    user: User = Depends(get_current_user),
) -> UserResponse:
    """Return the currently authenticated (forward-auth) user."""
    return UserResponse.model_validate(user)
