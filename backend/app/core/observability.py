"""Lightweight, structured backend observability (perf-telemetry).

Two signals, both emitted to **stdout** as logfmt-style ``key=value`` lines on
named loggers so the cluster's Loki can parse them with ``| logfmt`` (no HTTP
log shipper, no heavy dependency — stdlib :mod:`logging` only):

* **request timing** — one line per HTTP request (``app.request``) with the
  method, path, matched route template, status, duration, and the acting user
  identity; plus ``Server-Timing`` / ``X-Process-Time-Ms`` response headers so
  client devtools see the backend time;
* **slow queries** — one line per SQL statement (``app.slow_query``) whose
  execution exceeds :data:`Settings.SLOW_QUERY_MS`, with the elapsed time and the
  truncated statement text.

Everything here is defensive: a failure in the telemetry path must never break a
request or a query (the whole point is to *observe* prod, not add a new way for
it to fall over).
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.config import Settings, settings

# Named loggers — Loki labels/queries key off these. Kept distinct so each
# signal can be filtered independently.
REQUEST_LOGGER_NAME = "app.request"
SLOW_QUERY_LOGGER_NAME = "app.slow_query"

request_logger = logging.getLogger(REQUEST_LOGGER_NAME)
slow_query_logger = logging.getLogger(SLOW_QUERY_LOGGER_NAME)

# Marker so configure_logging / the slow-query listener are idempotent (callable
# more than once — e.g. across test app reuse — without double-wiring).
_HANDLER_MARKER = "_app_observability_handler"
_SLOW_QUERY_MARKER = "_app_slow_query_instrumented"

# Cap on the logged statement text. A SQL string can be large (a bulk COPY, a
# long IN-list); we want the shape, not the whole thing, and an unbounded log
# line is its own problem.
_MAX_STATEMENT_CHARS = 500

# conn.info key under which a statement's start time is stashed between the
# before/after cursor-execute events.
_QUERY_START_KEY = "_app_query_start_ns"


def _logfmt(**fields: Any) -> str:
    """Render fields as a logfmt-style ``key=value`` line.

    Values containing whitespace, ``"`` or ``=`` are double-quoted (with inner
    quotes escaped) so the line round-trips through ``| logfmt`` in LogQL. The
    ordering is the kwargs order (insertion-ordered).
    """
    parts: list[str] = []
    for key, value in fields.items():
        text = "-" if value is None else str(value)
        if text == "" or any(c in text for c in ' \t"='):
            text = '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
        parts.append(f"{key}={text}")
    return " ".join(parts)


def configure_logging(app_settings: Settings | None = None) -> None:
    """Configure the app's own loggers to emit logfmt lines to stdout.

    Idempotent: a handler we own is only added once (re-calling — e.g. when the
    test suite imports the app repeatedly — does nothing). Uvicorn's loggers are
    deliberately left untouched (we attach to *our* named loggers and disable
    propagation on them, rather than reconfiguring the root logger), so access
    logs / startup banners keep their own formatting.
    """
    cfg = app_settings or settings
    level = logging.getLevelNamesMapping().get(
        (cfg.LOG_LEVEL or "INFO").upper(), logging.INFO
    )

    for logger in (request_logger, slow_query_logger):
        logger.setLevel(level)
        # Don't bubble up to the root logger — we emit a fully-formed line and
        # don't want it duplicated/reformatted by a root handler (uvicorn's).
        logger.propagate = False
        already = any(
            getattr(h, _HANDLER_MARKER, False) for h in logger.handlers
        )
        if already:
            continue
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        setattr(handler, _HANDLER_MARKER, True)
        logger.addHandler(handler)


def identity_for_log(request: Request, app_settings: Settings | None = None) -> str:
    """The acting user's email for the request log — never raises.

    Mirrors :func:`app.core.dependencies._identity_email` (the forward-auth
    header, else ``DEV_AUTH_EMAIL``) but is **read-only and total**: it does no
    DB lookup and returns ``"-"`` when no identity is present, so the timing
    middleware can log an anonymous/unauthenticated request without blowing up.
    """
    cfg = app_settings or settings
    try:
        raw = request.headers.get(cfg.AUTH_EMAIL_HEADER) or cfg.DEV_AUTH_EMAIL
        email = (raw or "").strip().lower()
        return email or "-"
    except Exception:  # pragma: no cover - defensive; headers access shouldn't fail
        return "-"


def _route_template(request: Request) -> str:
    """The matched route's path template (e.g. ``/api/sessions/{id}``).

    Falls back to the raw path when no route matched (404) or the route exposes
    no path, so a high-cardinality id never explodes the log/label space when a
    template is available, but we still record *something* otherwise.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or request.url.path


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Log one timing line per request + set backend-timing response headers.

    The duration is measured around ``call_next``; on the response we set
    ``Server-Timing: app;dur=<ms>`` (read by Chrome/Firefox devtools' Timing
    tab) and ``X-Process-Time-Ms`` (simple, scriptable). An exception bubbling
    out of the handler is still logged (status 500) and re-raised — the
    middleware observes, it never swallows.
    """

    def __init__(self, app: ASGIApp, app_settings: Settings | None = None) -> None:
        super().__init__(app)
        self._settings = app_settings or settings

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000.0
            self._log(request, status_code=500, duration_ms=duration_ms)
            raise
        duration_ms = (time.perf_counter() - start) * 1000.0
        try:
            response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"
            response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"
        except Exception:  # pragma: no cover - defensive; never fail the response
            pass
        self._log(request, status_code=response.status_code, duration_ms=duration_ms)
        return response

    def _log(self, request: Request, *, status_code: int, duration_ms: float) -> None:
        # Logging must never break a request — swallow anything that goes wrong
        # building or emitting the line.
        try:
            request_logger.info(
                _logfmt(
                    method=request.method,
                    path=request.url.path,
                    route=_route_template(request),
                    status=status_code,
                    dur_ms=round(duration_ms, 1),
                    user=identity_for_log(request, self._settings),
                )
            )
        except Exception:  # pragma: no cover - defensive
            pass


def register_slow_query_logging(
    async_engine: AsyncEngine, app_settings: Settings | None = None
) -> None:
    """Attach slow-query logging to an async engine's underlying sync engine.

    SQLAlchemy's ``before_cursor_execute`` / ``after_cursor_execute`` events fire
    on the **sync** engine that backs the async one
    (:attr:`AsyncEngine.sync_engine`). We stash a per-execution start time on
    ``conn.info`` in ``before`` and, in ``after``, log a single line if the
    elapsed time exceeds the threshold. Idempotent (guarded by a marker on the
    sync engine) and fully defensive — a hiccup here never disturbs the query.
    """
    cfg = app_settings or settings
    sync_engine: Engine = async_engine.sync_engine
    if getattr(sync_engine, _SLOW_QUERY_MARKER, False):
        return
    setattr(sync_engine, _SLOW_QUERY_MARKER, True)

    threshold_ms = cfg.SLOW_QUERY_MS

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before_cursor_execute(  # noqa: ANN202 - SQLAlchemy event signature
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        # A connection can run nested executions; conn.info is per-connection
        # and statements on one connection are serial, so a single slot is safe.
        conn.info[_QUERY_START_KEY] = time.perf_counter()

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after_cursor_execute(  # noqa: ANN202 - SQLAlchemy event signature
        conn: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        try:
            start = conn.info.pop(_QUERY_START_KEY, None)
            if start is None:
                return
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            if elapsed_ms <= threshold_ms:
                return
            slow_query_logger.warning(
                _logfmt(
                    dur_ms=round(elapsed_ms, 1),
                    executemany=executemany,
                    statement=_truncate_statement(statement),
                )
            )
        except Exception:  # pragma: no cover - defensive; never disturb the query
            pass


def _truncate_statement(statement: str) -> str:
    """Collapse whitespace and cap the statement so the log line stays sane.

    Bound parameters are intentionally omitted (they can carry PII and bloat the
    line) — the statement shape is what identifies a slow query.
    """
    flat = " ".join((statement or "").split())
    if len(flat) > _MAX_STATEMENT_CHARS:
        return flat[:_MAX_STATEMENT_CHARS] + "…"
    return flat
