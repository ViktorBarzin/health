import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from collections.abc import AsyncIterator
from datetime import datetime, timezone

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
from app.database import async_session, engine
from app.services.analysis import get_analysis_provider, run_weekly_analysis
from app.services.push import push_config
from app.services.push_query import deliver_due

# Configure structured stdout logging + slow-query instrumentation once, at
# import time, so it's in place for both the app and any management command that
# imports the engine (perf-telemetry).
configure_logging(settings)
register_slow_query_logging(engine, settings)

_push_logger = logging.getLogger("app.push")

# The delivery poller's cadence. Rest timers are 60–180 s, so ±1 s of jitter on
# the buzz is invisible; the due-row claim uses SKIP LOCKED, so every replica
# can poll at this rate without double-sending (ADR-0010).
_PUSH_POLL_SECONDS = 1.0


async def _push_poller() -> None:
    """Deliver due rest-timer pushes forever (one task per app process)."""
    config = push_config(settings)
    if config is None:
        return  # fail closed: no VAPID identity deployed, nothing to run
    while True:
        await asyncio.sleep(_PUSH_POLL_SECONDS)
        try:
            async with async_session() as db:
                async with db.begin():
                    await deliver_due(
                        db, now=datetime.now(timezone.utc), config=config
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # never let one bad tick kill the loop
            _push_logger.exception("push delivery tick failed")


_analysis_logger = logging.getLogger("app.analysis")

# The weekly coach's-notes cadence: a coarse tick is plenty — run_weekly_analysis
# self-gates (one report per Program training week), so most ticks are no-ops.
_ANALYSIS_POLL_SECONDS = 1800.0


async def _analysis_poller() -> None:
    """Produce missing weekly coach's notes for every active Program."""
    if not settings.ANALYSIS_ENABLED:
        return
    from sqlalchemy import select

    from app.models.program import Program, ProgramStatus

    provider = get_analysis_provider()
    while True:
        await asyncio.sleep(_ANALYSIS_POLL_SECONDS)
        try:
            async with async_session() as db:
                user_ids = (
                    (
                        await db.execute(
                            select(Program.user_id).where(
                                Program.status == ProgramStatus.active
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
            for user_id in user_ids:
                try:
                    async with async_session() as db:
                        async with db.begin():
                            await run_weekly_analysis(
                                db,
                                user_id,
                                now=datetime.now(timezone.utc),
                                provider=provider,
                            )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    _analysis_logger.exception(
                        "weekly analysis failed for user %s", user_id
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            _analysis_logger.exception("analysis poll tick failed")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    poller = asyncio.create_task(_push_poller())
    analysis = asyncio.create_task(_analysis_poller())
    try:
        yield
    finally:
        for task in (poller, analysis):
            task.cancel()
        for task in (poller, analysis):
            with suppress(asyncio.CancelledError):
                await task


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
