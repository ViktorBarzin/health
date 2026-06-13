"""Nutrition #22 API: barcode→OFF→cache, custom Foods, Recipes, logging a Recipe.

DB-backed (real Postgres), OFF mocked (never the network). Covers:

* ``GET /barcode/{code}`` — first scan resolves via OFF and caches a shared Food;
  re-scan hits the cache (no network); not-found / incomplete → 404 (manual entry).
* custom Foods — create/edit/delete a private ``source='custom'`` Food, per-user
  visibility, and editing one recomputes a Recipe that uses it.
* Recipes — create with computed per-serving macros; a Recipe is loggable to the
  diary exactly like a Food; per-user privacy; delete.
"""

import uuid

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import app.services.off_lookup as off_lookup
from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.food import Food
from app.models.user import User

_NUTELLA = {
    "code": "3017624010701",
    "status": 1,
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


async def _make_user(db, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


async def _make_food(db, name, *, user_id=None, calories=100, protein_g=10, carbs_g=5, fat_g=2):
    f = Food(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        user_id=user_id,
        serving_size=100,
        serving_unit="g",
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        source="generic" if user_id is None else "custom",
    )
    db.add(f)
    await db.flush()
    return f


@pytest.fixture
async def client(db_session):
    """An AsyncClient bound to the test session with a switchable identity."""
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


@pytest.fixture(autouse=True)
def off_mock(monkeypatch):
    """Force the OFF HTTP call through a per-test MockTransport (never network).

    The API's barcode route calls ``off_lookup.lookup_barcode`` without a
    transport; we monkeypatch the module's ``httpx.AsyncClient`` to inject one,
    and count the network calls so cache-hit tests can assert "no extra call".
    """
    state = {"payload": _NUTELLA, "status": 200, "calls": []}

    real_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        state["calls"].append(1)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(state["status"], json=state["payload"])

        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(off_lookup.httpx, "AsyncClient", _factory)
    return state


# --------------------------------------------------------------------------- #
# Barcode → OFF → cache
# --------------------------------------------------------------------------- #


async def test_barcode_first_scan_resolves_and_caches(client, db_session, off_mock) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)

    resp = await client.get("/api/nutrition/barcode/3017624010701")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Nutella"
    assert body["brand"] == "Ferrero"
    assert body["source"] == "off"
    assert body["calories"] == 539
    assert len(off_mock["calls"]) == 1  # one network round-trip


async def test_barcode_rescan_hits_cache_no_network(client, db_session, off_mock) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)

    await client.get("/api/nutrition/barcode/3017624010701")
    calls_after_first = len(off_mock["calls"])
    resp = await client.get("/api/nutrition/barcode/3017624010701")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Nutella"
    assert len(off_mock["calls"]) == calls_after_first  # no extra network call


async def test_barcode_cached_food_is_searchable(client, db_session, off_mock) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    await client.get("/api/nutrition/barcode/3017624010701")

    resp = await client.get("/api/nutrition/foods", params={"search": "nutella"})
    names = [f["name"] for f in resp.json()]
    assert "Nutella" in names


async def test_barcode_not_found_404(client, db_session, off_mock) -> None:
    off_mock["payload"] = {"code": "9999999999999", "status": 0}
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    resp = await client.get("/api/nutrition/barcode/9999999999999")
    assert resp.status_code == 404


async def test_barcode_invalid_code_422(client, db_session, off_mock) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    resp = await client.get("/api/nutrition/barcode/not-a-barcode")
    assert resp.status_code == 422
    assert len(off_mock["calls"]) == 0  # no network call for junk input


async def test_barcode_incomplete_macros_404(client, db_session, off_mock) -> None:
    off_mock["payload"] = {
        "code": "1111111",
        "status": 1,
        "product": {"product_name": "X", "nutriments": {"energy-kcal_100g": 100}},
    }
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    resp = await client.get("/api/nutrition/barcode/1111111")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Custom Foods
# --------------------------------------------------------------------------- #


async def test_create_custom_food(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    resp = await client.post(
        "/api/nutrition/foods",
        json={
            "name": "Grandma's Granola",
            "brand": "Homemade",
            "serving_size": 50,
            "serving_unit": "g",
            "calories": 220,
            "protein_g": 6,
            "carbs_g": 30,
            "fat_g": 9,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Grandma's Granola"
    assert body["is_custom"] is True
    assert body["source"] == "custom"


async def test_custom_food_is_private_to_owner(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    client.set_user(alice)
    created = (await client.post(
        "/api/nutrition/foods",
        json={"name": "Secret", "serving_size": 1, "serving_unit": "g",
              "calories": 1, "protein_g": 0, "carbs_g": 0, "fat_g": 0},
    )).json()

    client.set_user(bob)
    assert (await client.get(f"/api/nutrition/foods/{created['id']}")).status_code == 404
    names = [f["name"] for f in (await client.get("/api/nutrition/foods")).json()]
    assert "Secret" not in names


async def test_log_custom_food_to_diary(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    food = (await client.post(
        "/api/nutrition/foods",
        json={"name": "Shake", "serving_size": 1, "serving_unit": "scoop",
              "calories": 120, "protein_g": 24, "carbs_g": 3, "fat_g": 1},
    )).json()

    entry = await client.post(
        "/api/nutrition/entries",
        json={"food_id": food["id"], "entry_date": "2026-06-13", "meal": "snack", "quantity": 2},
    )
    assert entry.status_code == 201
    assert entry.json()["calories"] == 240  # 120 * 2


async def test_edit_custom_food(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    food = (await client.post(
        "/api/nutrition/foods",
        json={"name": "Bar", "serving_size": 1, "serving_unit": "bar",
              "calories": 200, "protein_g": 10, "carbs_g": 20, "fat_g": 8},
    )).json()

    resp = await client.patch(f"/api/nutrition/foods/{food['id']}", json={"calories": 250, "name": "Bar v2"})
    assert resp.status_code == 200
    assert resp.json()["calories"] == 250
    assert resp.json()["name"] == "Bar v2"


async def test_cannot_edit_shared_food(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    shared = await _make_food(db_session, "Shared Rice")  # user_id None
    client.set_user(alice)
    resp = await client.patch(f"/api/nutrition/foods/{shared.id}", json={"calories": 999})
    assert resp.status_code == 404  # not the caller's to edit


async def test_cannot_edit_another_users_custom_food(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    bobs = await _make_food(db_session, "Bob's", user_id=bob.id)
    client.set_user(alice)
    resp = await client.patch(f"/api/nutrition/foods/{bobs.id}", json={"calories": 999})
    assert resp.status_code == 404


async def test_delete_custom_food(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    food = (await client.post(
        "/api/nutrition/foods",
        json={"name": "Temp", "serving_size": 1, "serving_unit": "g",
              "calories": 1, "protein_g": 0, "carbs_g": 0, "fat_g": 0},
    )).json()
    assert (await client.delete(f"/api/nutrition/foods/{food['id']}")).status_code == 204
    assert (await client.get(f"/api/nutrition/foods/{food['id']}")).status_code == 404


async def test_cannot_delete_custom_food_in_use(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    food = (await client.post(
        "/api/nutrition/foods",
        json={"name": "Used", "serving_size": 1, "serving_unit": "g",
              "calories": 10, "protein_g": 0, "carbs_g": 0, "fat_g": 0},
    )).json()
    await client.post("/api/nutrition/entries",
                      json={"food_id": food["id"], "entry_date": "2026-06-13", "meal": "lunch"})
    resp = await client.delete(f"/api/nutrition/foods/{food['id']}")
    assert resp.status_code == 409  # RESTRICT — referenced by a Diary Entry


# --------------------------------------------------------------------------- #
# Recipes
# --------------------------------------------------------------------------- #


async def test_create_recipe_computes_macros(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    chicken = await _make_food(db_session, "Chicken", calories=165, protein_g=31, carbs_g=0, fat_g=3.6)
    rice = await _make_food(db_session, "Rice", calories=130, protein_g=2.7, carbs_g=28, fat_g=0.3)
    client.set_user(alice)

    resp = await client.post(
        "/api/nutrition/recipes",
        json={
            "name": "Chicken & Rice Bowl",
            "yield_servings": 4,
            "ingredients": [
                {"food_id": str(chicken.id), "quantity": 2},
                {"food_id": str(rice.id), "quantity": 1.5},
            ],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Chicken & Rice Bowl"
    assert body["calories"] == pytest.approx(525 / 4)
    assert body["protein_g"] == pytest.approx(66.05 / 4)
    assert len(body["ingredients"]) == 2
    assert body["ingredients"][0]["food_name"] == "Chicken"
    assert body["ingredients"][0]["calories"] == pytest.approx(330)  # 165*2


async def test_recipe_is_loggable_to_diary(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    a = await _make_food(db_session, "A", calories=100, protein_g=10, carbs_g=0, fat_g=0)
    client.set_user(alice)
    recipe = (await client.post(
        "/api/nutrition/recipes",
        json={"name": "R", "yield_servings": 2, "ingredients": [{"food_id": str(a.id), "quantity": 4}]},
    )).json()
    assert recipe["calories"] == 200  # 100*4/2

    entry = await client.post(
        "/api/nutrition/entries",
        json={"food_id": recipe["food_id"], "entry_date": "2026-06-13", "meal": "dinner", "quantity": 1},
    )
    assert entry.status_code == 201
    assert entry.json()["food_name"] == "R"
    assert entry.json()["calories"] == 200

    day = (await client.get("/api/nutrition/diary", params={"date": "2026-06-13"})).json()
    assert day["total"]["calories"] == 200


async def test_recipe_rejects_zero_yield(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    a = await _make_food(db_session, "A")
    client.set_user(alice)
    resp = await client.post(
        "/api/nutrition/recipes",
        json={"name": "R", "yield_servings": 0, "ingredients": [{"food_id": str(a.id), "quantity": 1}]},
    )
    assert resp.status_code == 422


async def test_recipe_rejects_no_ingredients(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    resp = await client.post(
        "/api/nutrition/recipes",
        json={"name": "Empty", "yield_servings": 1, "ingredients": []},
    )
    assert resp.status_code == 422


async def test_recipe_rejects_invisible_ingredient(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    bobs = await _make_food(db_session, "Bob's", user_id=bob.id)
    client.set_user(alice)
    resp = await client.post(
        "/api/nutrition/recipes",
        json={"name": "R", "yield_servings": 1, "ingredients": [{"food_id": str(bobs.id), "quantity": 1}]},
    )
    assert resp.status_code == 404


async def test_list_and_get_recipes_scoped_to_owner(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    a = await _make_food(db_session, "A")
    client.set_user(alice)
    recipe = (await client.post(
        "/api/nutrition/recipes",
        json={"name": "Alice's", "yield_servings": 1, "ingredients": [{"food_id": str(a.id), "quantity": 1}]},
    )).json()

    assert any(r["id"] == recipe["id"] for r in (await client.get("/api/nutrition/recipes")).json())
    client.set_user(bob)
    assert (await client.get("/api/nutrition/recipes")).json() == []
    assert (await client.get(f"/api/nutrition/recipes/{recipe['id']}")).status_code == 404


async def test_update_recipe_recomputes(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    a = await _make_food(db_session, "A", calories=100, protein_g=10, carbs_g=0, fat_g=0)
    b = await _make_food(db_session, "B", calories=200, protein_g=20, carbs_g=0, fat_g=0)
    client.set_user(alice)
    recipe = (await client.post(
        "/api/nutrition/recipes",
        json={"name": "R", "yield_servings": 1, "ingredients": [{"food_id": str(a.id), "quantity": 1}]},
    )).json()
    assert recipe["calories"] == 100

    resp = await client.patch(
        f"/api/nutrition/recipes/{recipe['id']}",
        json={"name": "R2", "yield_servings": 2,
              "ingredients": [{"food_id": str(a.id), "quantity": 1}, {"food_id": str(b.id), "quantity": 1}]},
    )
    assert resp.status_code == 200
    assert resp.json()["calories"] == 150  # (100+200)/2


async def test_editing_ingredient_food_updates_recipe_via_api(client, db_session) -> None:
    # End-to-end of the "stays correct if an ingredient is edited" rule.
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    ing = (await client.post(
        "/api/nutrition/foods",
        json={"name": "Flour", "serving_size": 100, "serving_unit": "g",
              "calories": 100, "protein_g": 3, "carbs_g": 20, "fat_g": 1},
    )).json()
    recipe = (await client.post(
        "/api/nutrition/recipes",
        json={"name": "Bread", "yield_servings": 2, "ingredients": [{"food_id": ing["id"], "quantity": 4}]},
    )).json()
    assert recipe["calories"] == 200  # 100*4/2

    await client.patch(f"/api/nutrition/foods/{ing['id']}", json={"calories": 150})
    refreshed = (await client.get(f"/api/nutrition/recipes/{recipe['id']}")).json()
    assert refreshed["calories"] == 300  # 150*4/2


async def test_delete_recipe(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    a = await _make_food(db_session, "A")
    client.set_user(alice)
    recipe = (await client.post(
        "/api/nutrition/recipes",
        json={"name": "R", "yield_servings": 1, "ingredients": [{"food_id": str(a.id), "quantity": 1}]},
    )).json()
    assert (await client.delete(f"/api/nutrition/recipes/{recipe['id']}")).status_code == 204
    assert (await client.get(f"/api/nutrition/recipes/{recipe['id']}")).status_code == 404
    assert (await client.get(f"/api/nutrition/foods/{recipe['food_id']}")).status_code == 404
