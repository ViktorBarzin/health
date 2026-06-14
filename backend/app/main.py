import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.router import router as api_router
from app.core.exceptions import register_exception_handlers
from app.core.observability import (
    RequestTimingMiddleware,
    configure_logging,
    register_slow_query_logging,
)
from app.database import engine

# Configure structured stdout logging + slow-query instrumentation once, at
# import time, so it's in place for both the app and any management command that
# imports the engine (perf-telemetry).
configure_logging(settings)
register_slow_query_logging(engine, settings)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    yield


app = FastAPI(title="Apple Health Data", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request-timing telemetry (perf-telemetry): emits one logfmt line per request
# and sets Server-Timing / X-Process-Time-Ms headers. Added after CORS, so in
# Starlette's outside-in stack it sits *inside* CORS — it times the route
# handler itself (not CORS preflight short-circuits), and the timing headers it
# sets pass back out through CORS unmodified.
app.add_middleware(RequestTimingMiddleware, app_settings=settings)

register_exception_handlers(app)
app.include_router(api_router)


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
