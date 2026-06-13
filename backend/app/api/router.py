"""Main API router that aggregates all sub-routers."""

from fastapi import APIRouter

from app.api.activity import router as activity_router
from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.exercises import router as exercises_router
from app.api.gym_profile import router as gym_profile_router
from app.api.ingestion import router as ingestion_router
from app.api.metrics import router as metrics_router
from app.api.principles import router as principles_router
from app.api.programs import router as programs_router
from app.api.readiness import router as readiness_router
from app.api.recommendations import router as recommendations_router
from app.api.sessions import router as sessions_router
from app.api.workouts import router as workouts_router

router = APIRouter()

router.include_router(auth_router, prefix="/api/auth", tags=["auth"])
router.include_router(metrics_router, prefix="/api/metrics", tags=["metrics"])
router.include_router(workouts_router, prefix="/api/workouts", tags=["workouts"])
router.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
router.include_router(activity_router, prefix="/api/activity", tags=["activity"])
router.include_router(ingestion_router, prefix="/api/import", tags=["import"])
router.include_router(exercises_router, prefix="/api/exercises", tags=["exercises"])
router.include_router(sessions_router, prefix="/api/sessions", tags=["sessions"])
router.include_router(analytics_router, prefix="/api/analytics", tags=["analytics"])
router.include_router(
    gym_profile_router, prefix="/api/gym-profile", tags=["gym-profile"]
)
router.include_router(
    recommendations_router, prefix="/api/recommendations", tags=["recommendations"]
)
router.include_router(
    principles_router, prefix="/api/principles", tags=["principles"]
)
router.include_router(programs_router, prefix="/api/programs", tags=["programs"])
router.include_router(
    readiness_router, prefix="/api/readiness", tags=["readiness"]
)
