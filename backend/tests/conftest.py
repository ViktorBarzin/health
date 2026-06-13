"""Shared pytest fixtures.

Env vars must be set before importing app modules (pydantic Settings reads at
import time). DB-backed tests run against a real Postgres because the models use
Postgres-specific column types (UUID, JSONB, LargeBinary); point them at one via
``TEST_DATABASE_URL`` (defaults to the throwaway local container used in CI/dev).
"""

import os

# A throwaway local Postgres is the default; override with TEST_DATABASE_URL.
_DEFAULT_TEST_DB = "postgresql+asyncpg://health:test@localhost:55432/apple_health_test"
os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", _DEFAULT_TEST_DB))

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.models import User  # noqa: F401 - ensure all models register on Base


def _sync_url() -> str:
    """The sync (psycopg2) form of the configured async DATABASE_URL."""
    return os.environ["DATABASE_URL"].replace("+asyncpg", "")


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A clean database for one test: create_all on a fresh engine, drop after.

    Each test gets the full schema created from the ORM metadata and an open
    session bound to it; the schema is torn down afterwards so tests do not
    leak rows into one another.
    """
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=None)
    # DROP SCHEMA (not metadata drop_all) so any table left by a prior alembic
    # run — e.g. a stale user_credentials with an FK to users — can't block
    # create_all.
    async with engine.begin() as conn:
        await conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        await conn.exec_driver_sql("CREATE SCHEMA public")
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as session:
            yield session
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
def sync_engine() -> Iterator[Engine]:
    """A sync engine on a freshly-emptied schema, for migration-logic tests.

    The reconciliation runs over a sync Connection (as Alembic does via
    Connection.run_sync), so its tests build the schema and assert through a
    plain sync engine. The public schema is dropped and recreated up front so a
    leftover table from a prior alembic run can't block ``create_all``.
    """
    engine = create_engine(_sync_url())
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql("DROP SCHEMA public CASCADE")
            conn.exec_driver_sql("CREATE SCHEMA public")
        engine.dispose()
