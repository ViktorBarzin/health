"""OFF barcode lookup: fetch-then-cache, cache-hit, not-found / incomplete.

These are DB-backed (real Postgres via ``db_session``) but **never hit the
network** — the OFF HTTP call is mocked with an ``httpx.MockTransport`` (the same
pattern as the claude-agent tests). They pin the cache contract from the
acceptance criteria:

* first lookup fetches OFF, maps it, and persists a shared ``source='off'`` Food;
* a second lookup of the same barcode returns the cached Food and makes **no
  network call** (the handler asserts it isn't called again);
* a not-found product (OFF ``status: 0``) and a product with incomplete macros
  resolve to None and write **no** Food (the caller falls back to manual entry);
* the persisted Food is shared (``user_id IS NULL``) so every user reuses it.
"""

import httpx
from sqlalchemy import func, select

from app.models.food import Food
from app.services.off_lookup import lookup_barcode

_NUTELLA = {
    "code": "3017624010701",
    "status": 1,
    "status_verbose": "product found",
    "product": {
        "product_name": "Nutella",
        "brands": "Ferrero",
        "nutriments": {
            "energy-kcal_100g": 539,
            "proteins_100g": 6.7,
            "carbohydrates_100g": 57.5,
            "fat_100g": 30.9,
        },
    },
}


def _transport_returning(payload, *, status=200, counter=None):
    """A MockTransport that returns ``payload`` and counts calls (optional)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if counter is not None:
            counter.append(request.url)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def _failing_transport():
    """A MockTransport that fails the test if the network is touched."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"network was called: {request.url}")

    return httpx.MockTransport(handler)


async def test_first_lookup_fetches_and_caches_a_food(db_session) -> None:
    calls: list = []
    food = await lookup_barcode(
        db_session,
        "3017624010701",
        transport=_transport_returning(_NUTELLA, counter=calls),
    )
    assert food is not None
    assert food.name == "Nutella"
    assert food.brand == "Ferrero"
    assert food.source == "off"
    assert food.off_id == "3017624010701"
    assert food.user_id is None  # shared catalog row
    assert food.calories == 539
    assert food.serving_size == 100.0
    assert len(calls) == 1  # one network round-trip

    # It was persisted as a Food.
    count = (await db_session.execute(select(func.count()).select_from(Food))).scalar()
    assert count == 1


async def test_second_lookup_hits_cache_no_network(db_session) -> None:
    # Seed the cache via a first (mocked) fetch.
    await lookup_barcode(
        db_session, "3017624010701", transport=_transport_returning(_NUTELLA)
    )

    # The second lookup must NOT touch the network — the transport asserts it.
    food = await lookup_barcode(
        db_session, "3017624010701", transport=_failing_transport()
    )
    assert food is not None
    assert food.name == "Nutella"

    # Still exactly one Food row (no duplicate cached).
    count = (await db_session.execute(select(func.count()).select_from(Food))).scalar()
    assert count == 1


async def test_not_found_returns_none_and_writes_nothing(db_session) -> None:
    not_found = {"code": "0000", "status": 0, "status_verbose": "product not found"}
    food = await lookup_barcode(
        db_session, "0000", transport=_transport_returning(not_found)
    )
    assert food is None
    count = (await db_session.execute(select(func.count()).select_from(Food))).scalar()
    assert count == 0  # no garbage Food written


async def test_incomplete_macros_returns_none_and_writes_nothing(db_session) -> None:
    incomplete = {
        "code": "111",
        "status": 1,
        "product": {
            "product_name": "Mystery",
            "nutriments": {"energy-kcal_100g": 200},  # no protein/carbs/fat
        },
    }
    food = await lookup_barcode(
        db_session, "111", transport=_transport_returning(incomplete)
    )
    assert food is None
    count = (await db_session.execute(select(func.count()).select_from(Food))).scalar()
    assert count == 0


async def test_http_error_returns_none(db_session) -> None:
    food = await lookup_barcode(
        db_session, "3017624010701",
        transport=_transport_returning({"detail": "down"}, status=503),
    )
    assert food is None
    count = (await db_session.execute(select(func.count()).select_from(Food))).scalar()
    assert count == 0


async def test_cached_food_is_visible_to_any_user(db_session) -> None:
    # The cached Food is shared (user_id NULL), so it shows up in any user's
    # catalog search (global ∪ own). We assert the row is shared here; the API
    # test covers the search path.
    food = await lookup_barcode(
        db_session, "3017624010701", transport=_transport_returning(_NUTELLA)
    )
    assert food is not None
    assert food.user_id is None
