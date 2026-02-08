"""Main API router that aggregates all sub-routers."""

from fastapi import APIRouter

from app.api.activity import router as activity_router
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.ingestion import router as ingestion_router
from app.api.metrics import router as metrics_router
from app.api.workouts import router as workouts_router

router = APIRouter()

router.include_router(auth_router, prefix="/api/auth", tags=["auth"])
router.include_router(metrics_router, prefix="/api/metrics", tags=["metrics"])
router.include_router(workouts_router, prefix="/api/workouts", tags=["workouts"])
router.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
router.include_router(activity_router, prefix="/api/activity", tags=["activity"])
router.include_router(ingestion_router, prefix="/api/import", tags=["import"])
