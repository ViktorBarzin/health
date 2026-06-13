"""Principles KB API contract (#14 receipts UI taps this; auth-gated).

- GET /api/principles lists the catalog; goal/experience scopes it to a context;
  category narrows it.
- GET /api/principles/categories returns the typed category dimension.
- GET /api/principles/{key} returns one rule with its params + citations; 404 for
  an unknown key.
- Endpoints require an authenticated user.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.principle import (
    EvidenceGrade,
    ExperienceLevel,
    Principle,
    PrincipleCategory,
    PrincipleCitation,
    TrainingGoal,
)
from app.models.user import User


def _principle(
    key: str,
    *,
    category: PrincipleCategory,
    goals: list[str],
    levels: list[str],
    params: dict | None = None,
) -> Principle:
    return Principle(
        key=key,
        statement=f"Statement for {key}.",
        category=category,
        params=params or {},
        goals=goals,
        experience_levels=levels,
        evidence_grade=EvidenceGrade.A,
        version=1,
    )


@pytest.fixture
async def client(db_session):
    state = {"user": None}

    async def _override_db():
        yield db_session

    async def _override_user():
        return state["user"]

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.set_user = lambda u: state.__setitem__("user", u)  # type: ignore[attr-defined]
        yield ac
    app.dependency_overrides.clear()


async def _make_user(db, email: str = "lifter@example.com") -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


async def _seed(db) -> None:
    volume = _principle(
        "volume",
        category=PrincipleCategory.volume,
        goals=[TrainingGoal.bulk.value, TrainingGoal.strength.value],
        levels=[],
        params={"sets_per_muscle_per_week": {"min": 10, "max": 20, "unit": "sets"}},
    )
    volume.citations.append(
        PrincipleCitation(
            authors="Schoenfeld BJ, et al.",
            year=2017,
            title="Dose-response volume meta-analysis",
            journal="Journal of Sports Sciences",
            doi="10.1080/02640414.2016.1210197",
            pmid="27433992",
        )
    )
    db.add_all(
        [
            volume,
            _principle(
                "progressive-overload",
                category=PrincipleCategory.progression,
                goals=[],
                levels=[],
                params={"load_increase_percent": {"min": 2, "max": 10, "unit": "%"}},
            ),
            _principle(
                "protein",
                category=PrincipleCategory.nutrition,
                goals=[TrainingGoal.bulk.value, TrainingGoal.maintain.value],
                levels=[],
            ),
        ]
    )
    await db.flush()


async def test_requires_auth(db_session) -> None:
    """With no forward-auth header (and no dev override), the endpoint is 401.

    Unlike the ``client`` fixture, this exercises the *real* ``get_current_user``
    — only ``get_db`` is overridden — so a request with no identity hits the 401
    the dependency raises, confirming the router is auth-gated.
    """

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/principles/")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides.clear()


async def test_list_returns_full_catalog(client, db_session) -> None:
    client.set_user(await _make_user(db_session))
    await _seed(db_session)

    resp = await client.get("/api/principles/")
    assert resp.status_code == 200
    keys = {p["key"] for p in resp.json()}
    assert keys == {"volume", "progressive-overload", "protein"}


async def test_list_scoped_to_context(client, db_session) -> None:
    client.set_user(await _make_user(db_session))
    await _seed(db_session)

    # A cut excludes the gain-goal rules but keeps the universal one.
    resp = await client.get("/api/principles/?goal=cut&experience=beginner")
    assert resp.status_code == 200
    keys = {p["key"] for p in resp.json()}
    assert keys == {"progressive-overload"}

    # A bulk includes volume + protein + the universal rule.
    resp = await client.get("/api/principles/?goal=bulk&experience=beginner")
    keys = {p["key"] for p in resp.json()}
    assert keys == {"volume", "protein", "progressive-overload"}


async def test_list_category_filter(client, db_session) -> None:
    client.set_user(await _make_user(db_session))
    await _seed(db_session)

    resp = await client.get("/api/principles/?category=nutrition")
    assert resp.status_code == 200
    assert [p["key"] for p in resp.json()] == ["protein"]


async def test_categories_endpoint(client, db_session) -> None:
    client.set_user(await _make_user(db_session))
    resp = await client.get("/api/principles/categories")
    assert resp.status_code == 200
    values = {c["value"] for c in resp.json()}
    # All typed categories are offered.
    assert {"volume", "frequency", "intensity", "progression", "nutrition"} <= values


async def test_get_by_key_returns_params_and_citations(client, db_session) -> None:
    client.set_user(await _make_user(db_session))
    await _seed(db_session)

    resp = await client.get("/api/principles/volume")
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "volume"
    assert body["evidence_grade"] == "A"
    # Structured params serialize as typed ranges.
    assert body["params"]["sets_per_muscle_per_week"] == {
        "min": 10.0,
        "max": 20.0,
        "value": None,
        "unit": "sets",
    }
    assert body["goals"] == ["bulk", "strength"]
    # Citation comes through with a resolvable link.
    assert len(body["citations"]) == 1
    cite = body["citations"][0]
    assert cite["pmid"] == "27433992"
    assert cite["resolved_url"] == "https://doi.org/10.1080/02640414.2016.1210197"


async def test_get_by_key_unknown_is_404(client, db_session) -> None:
    client.set_user(await _make_user(db_session))
    await _seed(db_session)
    resp = await client.get("/api/principles/nope")
    assert resp.status_code == 404
