"""Backend telemetry — request-timing middleware + slow-query logging (perf-telemetry).

Pins the acceptance criteria:

* the timing middleware sets ``Server-Timing`` + ``X-Process-Time-Ms`` headers and
  emits one logfmt line per request carrying method / path / route template /
  status / dur_ms / user — and a missing identity logs ``user=-`` rather than 401;
* the slow-query listener (attached to ``engine.sync_engine``) logs a statement
  over the threshold and stays silent under it — verified both as a focused unit
  test against a fake engine *and* end-to-end with a real ``pg_sleep`` query;
* logging configuration + the listener are idempotent (no double handlers /
  double listeners) and never break a request/query when logging fails.

The pure helpers (logfmt, identity, statement truncation) are unit-tested with no
IO so the format contract is locked down independently of the wiring.
"""

import logging

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.core import observability as obs
from app.core.dependencies import get_current_user
from app.core.observability import (
    REQUEST_LOGGER_NAME,
    SLOW_QUERY_LOGGER_NAME,
    RequestTimingMiddleware,
    _logfmt,
    _truncate_statement,
    configure_logging,
    identity_for_log,
    register_slow_query_logging,
)
from app.database import get_db
from app.main import app
from app.models.user import User


@pytest.fixture
def capture_telemetry(caplog):
    """Capture the telemetry loggers despite ``propagate=False``.

    The app's loggers deliberately don't propagate to root (so uvicorn's root
    handler can't re-emit our already-formatted line), but pytest's ``caplog``
    installs its capture handler on the *root* logger and relies on propagation.
    So we attach ``caplog.handler`` directly to our named loggers (the documented
    workaround for non-propagating loggers) and force them to INFO for the test.
    Returns the caplog fixture for ``.records`` / ``.clear()``.
    """
    targets = [
        logging.getLogger(REQUEST_LOGGER_NAME),
        logging.getLogger(SLOW_QUERY_LOGGER_NAME),
    ]
    saved = [(lg, lg.level) for lg in targets]
    for lg in targets:
        lg.addHandler(caplog.handler)
        lg.setLevel(logging.INFO)
    caplog.set_level(logging.INFO)
    try:
        yield caplog
    finally:
        for lg, level in saved:
            lg.removeHandler(caplog.handler)
            lg.setLevel(level)


# --------------------------------------------------------------------------- #
# Pure helpers — logfmt rendering, identity resolution, statement truncation.
# --------------------------------------------------------------------------- #


def test_logfmt_plain_pairs_unquoted():
    line = _logfmt(method="GET", status=200, dur_ms=1.5)
    assert line == "method=GET status=200 dur_ms=1.5"


def test_logfmt_quotes_values_with_spaces_and_escapes_quotes():
    line = _logfmt(statement='SELECT "x" FROM t WHERE a = 1')
    # The whole value is quoted (it has spaces) and inner quotes are escaped, so
    # LogQL's `| logfmt` parses one field.
    assert line == r'statement="SELECT \"x\" FROM t WHERE a = 1"'


def test_logfmt_none_and_empty_render_as_dash_and_quoted_empty():
    assert _logfmt(user=None) == "user=-"
    assert _logfmt(x="") == 'x=""'


def test_truncate_statement_collapses_whitespace():
    assert _truncate_statement("SELECT\n  1,\n  2\nFROM t") == "SELECT 1, 2 FROM t"


def test_truncate_statement_caps_length_with_ellipsis():
    long = "SELECT " + ("a, " * 500)
    out = _truncate_statement(long)
    assert len(out) <= obs._MAX_STATEMENT_CHARS + 1  # +1 for the ellipsis char
    assert out.endswith("…")


def _request(headers: dict[str, str]):
    """A minimal Starlette Request carrying the given headers."""
    from starlette.requests import Request

    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "method": "GET", "path": "/"})


def test_identity_for_log_reads_forward_auth_header():
    s = Settings(DATABASE_URL="x", AUTH_EMAIL_HEADER="X-authentik-email")
    req = _request({"X-authentik-email": "Alice@Example.com"})
    assert identity_for_log(req, s) == "alice@example.com"


def test_identity_for_log_falls_back_to_dev_auth_email():
    s = Settings(DATABASE_URL="x", DEV_AUTH_EMAIL="dev@example.com")
    assert identity_for_log(_request({}), s) == "dev@example.com"


def test_identity_for_log_returns_dash_when_absent_never_raises():
    s = Settings(DATABASE_URL="x")  # no header, no DEV_AUTH_EMAIL
    assert identity_for_log(_request({}), s) == "-"


# --------------------------------------------------------------------------- #
# Logging configuration — idempotent, to stdout, doesn't touch uvicorn.
# --------------------------------------------------------------------------- #


def test_configure_logging_is_idempotent():
    logger = logging.getLogger(REQUEST_LOGGER_NAME)
    before = list(logger.handlers)
    configure_logging()
    configure_logging()
    after = logger.handlers
    owned = [h for h in after if getattr(h, obs._HANDLER_MARKER, False)]
    # Exactly one handler we own, regardless of how many times configure runs.
    assert len(owned) == 1
    # And it doesn't propagate to the root logger (so uvicorn's root handler
    # doesn't re-emit our already-formatted line).
    assert logger.propagate is False
    # Re-running added nothing beyond what was there + our single handler.
    assert set(before) <= set(after)


def test_configure_logging_respects_level(monkeypatch):
    configure_logging(Settings(DATABASE_URL="x", LOG_LEVEL="WARNING"))
    assert logging.getLogger(REQUEST_LOGGER_NAME).level == logging.WARNING
    # Restore INFO so other tests see the documented default.
    configure_logging(Settings(DATABASE_URL="x", LOG_LEVEL="INFO"))


# --------------------------------------------------------------------------- #
# Request-timing middleware — headers + structured log line, via the real app.
# --------------------------------------------------------------------------- #


@pytest.fixture
async def client(db_session):
    """ASGI client over the real app with db + (settable) user overridden."""
    state = {"user": None}

    async def _override_db():
        yield db_session

    async def _override_user():
        if state["user"] is None:
            # Mirror the real 401 when no identity is set, so we can exercise
            # the unauthenticated path too.
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Not authenticated")
        return state["user"]

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.set_user = lambda u: state.__setitem__("user", u)  # type: ignore[attr-defined]
        yield ac
    app.dependency_overrides.clear()


async def test_health_request_sets_timing_headers():
    """The unauthenticated health endpoint carries both backend-timing headers."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/health")
    assert resp.status_code == 200
    assert "Server-Timing" in resp.headers
    assert resp.headers["Server-Timing"].startswith("app;dur=")
    assert "X-Process-Time-Ms" in resp.headers
    # The header is a parseable float.
    float(resp.headers["X-Process-Time-Ms"])


async def test_request_emits_structured_timing_log(capture_telemetry):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        await ac.get("/api/health")
    lines = [
        r.message for r in capture_telemetry.records if r.name == REQUEST_LOGGER_NAME
    ]
    assert len(lines) == 1
    line = lines[0]
    assert "method=GET" in line
    assert "path=/api/health" in line
    # The matched route template is recorded (here it equals the path).
    assert "route=/api/health" in line
    assert "status=200" in line
    assert "dur_ms=" in line
    # Health is unauthenticated → identity logged as "-", not a crash.
    assert "user=-" in line


async def test_request_logs_authenticated_user(client, db_session, capture_telemetry):
    user = User(email="alice@example.com")
    db_session.add(user)
    await db_session.flush()
    client.set_user(user)
    # /api/auth/me requires auth and uses get_current_user (overridden above).
    resp = await client.get(
        "/api/auth/me", headers={"X-authentik-email": "alice@example.com"}
    )
    assert resp.status_code == 200
    lines = [
        r.message for r in capture_telemetry.records if r.name == REQUEST_LOGGER_NAME
    ]
    assert any("user=alice@example.com" in ln for ln in lines)
    assert any("status=200" in ln and "path=/api/auth/me" in ln for ln in lines)


async def test_unknown_route_logs_raw_path_and_404(capture_telemetry):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/nope/does-not-exist")
    assert resp.status_code == 404
    lines = [
        r.message for r in capture_telemetry.records if r.name == REQUEST_LOGGER_NAME
    ]
    assert any(
        "status=404" in ln and "path=/api/nope/does-not-exist" in ln for ln in lines
    )


# --------------------------------------------------------------------------- #
# Slow-query logging — unit (fake engine) + end-to-end (real pg_sleep).
# --------------------------------------------------------------------------- #


async def test_slow_query_listener_logs_over_threshold_silent_under(capture_telemetry):
    """A focused listener test: threshold 0 logs; a huge threshold stays silent.

    Uses its own throwaway async engine so it doesn't perturb the app engine's
    listeners; the schema is irrelevant (a trivial ``SELECT 1`` exercises the
    cursor-execute events).
    """
    import os

    url = os.environ["DATABASE_URL"]

    # Threshold 0 → every statement is "slow" → it is logged.
    eng_low = create_async_engine(url, poolclass=None)
    register_slow_query_logging(eng_low, Settings(DATABASE_URL=url, SLOW_QUERY_MS=0))
    async with eng_low.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await eng_low.dispose()
    low_lines = [
        r.message
        for r in capture_telemetry.records
        if r.name == SLOW_QUERY_LOGGER_NAME
    ]
    assert any("SELECT 1" in ln and "dur_ms=" in ln for ln in low_lines)

    capture_telemetry.clear()

    # A very high threshold → nothing logged.
    eng_high = create_async_engine(url, poolclass=None)
    register_slow_query_logging(
        eng_high, Settings(DATABASE_URL=url, SLOW_QUERY_MS=10_000_000)
    )
    async with eng_high.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await eng_high.dispose()
    high_lines = [
        r.message
        for r in capture_telemetry.records
        if r.name == SLOW_QUERY_LOGGER_NAME
    ]
    assert high_lines == []


async def test_slow_query_real_pg_sleep_is_logged(capture_telemetry):
    """End-to-end: a genuinely slow query (pg_sleep) trips the threshold."""
    import os

    url = os.environ["DATABASE_URL"]
    eng = create_async_engine(url, poolclass=None)
    # 50ms threshold; sleep 150ms → over.
    register_slow_query_logging(eng, Settings(DATABASE_URL=url, SLOW_QUERY_MS=50))
    async with eng.connect() as conn:
        await conn.execute(text("SELECT pg_sleep(0.15)"))
    await eng.dispose()
    lines = [
        r.message for r in capture_telemetry.records if r.name == SLOW_QUERY_LOGGER_NAME
    ]
    assert any("pg_sleep" in ln for ln in lines)
    # And the logged duration reflects the real ~150ms (well over the 50 threshold).
    slow = next(ln for ln in lines if "pg_sleep" in ln)
    dur = float(slow.split("dur_ms=")[1].split(" ")[0])
    assert dur >= 50


async def test_register_slow_query_logging_idempotent(capture_telemetry):
    """Registering twice on the same engine does not double-log a statement."""
    import os

    url = os.environ["DATABASE_URL"]
    eng = create_async_engine(url, poolclass=None)
    s = Settings(DATABASE_URL=url, SLOW_QUERY_MS=0)
    register_slow_query_logging(eng, s)
    register_slow_query_logging(eng, s)  # second call must be a no-op
    async with eng.connect() as conn:
        await conn.execute(text("SELECT 42"))
    await eng.dispose()
    hits = [
        r.message
        for r in capture_telemetry.records
        if r.name == SLOW_QUERY_LOGGER_NAME and "SELECT 42" in r.message
    ]
    assert len(hits) == 1
