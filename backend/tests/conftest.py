"""Shared test fixtures for the Apple Health backend test suite.

Provides:
- ``engine``  -- session-scoped async engine against a test database
- ``db_session`` -- function-scoped session with automatic rollback
- ``client`` -- unauthenticated ``httpx.AsyncClient`` wired to the ASGI app
- ``authenticated_client`` -- same, but with a pre-seeded user and session cookie
"""

import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.core.auth import create_session

# Import all models so Base.metadata knows about every table
from app.models.user import User  # noqa: F401
from app.models.user_credential import UserCredential  # noqa: F401
from app.models.data_source import DataSource  # noqa: F401
from app.models.import_batch import ImportBatch  # noqa: F401
from app.models.health_record import HealthRecord  # noqa: F401
from app.models.category_record import CategoryRecord  # noqa: F401
from app.models.workout import Workout  # noqa: F401
from app.models.workout_route_point import WorkoutRoutePoint  # noqa: F401
from app.models.activity_summary import ActivitySummary  # noqa: F401

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://health:changeme@localhost:5432/apple_health_test",
)


@pytest.fixture(scope="session")
def event_loop():
    """Create a single event loop shared across the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create tables at session start, drop them at teardown."""
    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def db_session(engine):
    """Provide a transactional session that rolls back after each test."""
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    """Unauthenticated ASGI test client with the DB dependency overridden."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authenticated_client(db_session):
    """ASGI test client with a pre-seeded user and valid session cookie."""
    # Create a test user
    user = User(email="test@example.com")
    db_session.add(user)
    await db_session.flush()
    await db_session.commit()
    await db_session.refresh(user, attribute_names=["id"])

    # Create an in-memory session token
    token = create_session(user.id)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        cookies={"session": token},
    ) as ac:
        yield ac
    app.dependency_overrides.clear()
