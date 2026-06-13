"""Nutrition API: Food catalog search + Diary CRUD + per-user scoping + totals.

- Search the shared Food catalog (global ∪ the caller's own custom, later #22).
- Log / list / edit / delete a Diary Entry (a Food + quantity → a Meal of a day).
- The day view groups entries by Meal with per-meal subtotals and a day total,
  computed as Σ (Food per-serving macros × quantity).
- A history endpoint gives per-day totals over a date range.
- A user can never read or mutate another user's Diary Entries.
"""

import datetime as dt
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.food import Food
from app.models.user import User


async def _make_user(db, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


async def _make_food(
    db,
    name: str,
    *,
    user_id=None,
    serving_size=100.0,
    serving_unit="g",
    calories=165.0,
    protein_g=31.0,
    carbs_g=0.0,
    fat_g=3.6,
) -> Food:
    food = Food(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        user_id=user_id,
        serving_size=serving_size,
        serving_unit=serving_unit,
        calories=calories,
        protein_g=protein_g,
        carbs_g=carbs_g,
        fat_g=fat_g,
        source="generic" if user_id is None else "custom",
    )
    db.add(food)
    await db.flush()
    return food


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


# --------------------------------------------------------------------------- #
# Food catalog search
# --------------------------------------------------------------------------- #


async def test_search_foods_returns_matches(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    await _make_food(db_session, "Chicken breast, cooked")
    await _make_food(db_session, "White rice, cooked")
    await _make_food(db_session, "Banana", serving_unit="medium", calories=105)
    client.set_user(alice)

    resp = await client.get("/api/nutrition/foods", params={"search": "rice"})
    assert resp.status_code == 200
    names = [f["name"] for f in resp.json()]
    assert names == ["White rice, cooked"]


async def test_search_foods_lists_all_when_no_query(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    await _make_food(db_session, "Chicken breast, cooked")
    await _make_food(db_session, "Banana")
    client.set_user(alice)

    resp = await client.get("/api/nutrition/foods")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_food_catalog_hides_other_users_custom_foods(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    # A shared generic Food, plus one private custom Food owned by Bob.
    await _make_food(db_session, "Shared Oats")
    await _make_food(db_session, "Bob's Secret Shake", user_id=bob.id)
    client.set_user(alice)

    resp = await client.get("/api/nutrition/foods")
    names = [f["name"] for f in resp.json()]
    assert "Shared Oats" in names
    assert "Bob's Secret Shake" not in names  # not Alice's


async def test_get_food_detail(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    food = await _make_food(db_session, "Egg, large", serving_size=1, serving_unit="egg",
                            calories=72, protein_g=6.3, carbs_g=0.4, fat_g=4.8)
    client.set_user(alice)

    resp = await client.get(f"/api/nutrition/foods/{food.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Egg, large"
    assert body["serving_unit"] == "egg"
    assert body["calories"] == 72
    assert body["is_custom"] is False


# --------------------------------------------------------------------------- #
# Diary Entry CRUD
# --------------------------------------------------------------------------- #


async def test_create_diary_entry_scales_macros_by_quantity(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    chicken = await _make_food(db_session, "Chicken breast, cooked")  # 165/31/0/3.6 per 100g
    client.set_user(alice)

    resp = await client.post(
        "/api/nutrition/entries",
        json={
            "food_id": str(chicken.id),
            "entry_date": "2026-06-13",
            "meal": "lunch",
            "quantity": 1.5,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["food_name"] == "Chicken breast, cooked"
    assert body["meal"] == "lunch"
    assert body["quantity"] == 1.5
    # Macros scaled by quantity: 165*1.5 = 247.5, 31*1.5 = 46.5
    assert body["calories"] == 247.5
    assert body["protein_g"] == 46.5
    assert body["fat_g"] == 5.4


async def test_create_diary_entry_defaults_quantity_to_one(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    egg = await _make_food(db_session, "Egg", serving_size=1, serving_unit="egg",
                           calories=72, protein_g=6.3, carbs_g=0.4, fat_g=4.8)
    client.set_user(alice)

    resp = await client.post(
        "/api/nutrition/entries",
        json={"food_id": str(egg.id), "entry_date": "2026-06-13", "meal": "breakfast"},
    )
    assert resp.status_code == 201
    assert resp.json()["quantity"] == 1.0
    assert resp.json()["calories"] == 72


async def test_create_entry_with_unknown_food_404s(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    resp = await client.post(
        "/api/nutrition/entries",
        json={
            "food_id": str(uuid.uuid4()),
            "entry_date": "2026-06-13",
            "meal": "lunch",
        },
    )
    assert resp.status_code == 404


async def test_cannot_log_another_users_custom_food(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    bobs_food = await _make_food(db_session, "Bob's Shake", user_id=bob.id)
    client.set_user(alice)

    resp = await client.post(
        "/api/nutrition/entries",
        json={
            "food_id": str(bobs_food.id),
            "entry_date": "2026-06-13",
            "meal": "snack",
        },
    )
    # Alice can't see Bob's private Food, so logging it is a 404 (no leak).
    assert resp.status_code == 404


async def test_update_diary_entry_quantity_recomputes_macros(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    chicken = await _make_food(db_session, "Chicken")  # 165 per 100g
    client.set_user(alice)
    entry = (await client.post(
        "/api/nutrition/entries",
        json={"food_id": str(chicken.id), "entry_date": "2026-06-13", "meal": "lunch", "quantity": 1},
    )).json()

    resp = await client.patch(
        f"/api/nutrition/entries/{entry['id']}", json={"quantity": 2}
    )
    assert resp.status_code == 200
    assert resp.json()["quantity"] == 2
    assert resp.json()["calories"] == 330  # 165 * 2


async def test_update_diary_entry_can_swap_food_and_recomputes(client, db_session) -> None:
    # The edit sheet sends food_id; swapping the Food must reload the relationship
    # so the returned macros reflect the NEW Food, not the old one.
    alice = await _make_user(db_session, "alice@example.com")
    chicken = await _make_food(db_session, "Chicken")  # 165/31/0/3.6 per 100g
    rice = await _make_food(db_session, "Rice", calories=130, protein_g=2.7, carbs_g=28, fat_g=0.3)
    client.set_user(alice)
    entry = (await client.post(
        "/api/nutrition/entries",
        json={"food_id": str(chicken.id), "entry_date": "2026-06-13", "meal": "lunch", "quantity": 1},
    )).json()
    assert entry["food_name"] == "Chicken"

    resp = await client.patch(
        f"/api/nutrition/entries/{entry['id']}", json={"food_id": str(rice.id)}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["food_name"] == "Rice"
    assert body["calories"] == 130  # the NEW food's per-serving macros × 1


async def test_cannot_swap_to_another_users_food(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    shared = await _make_food(db_session, "Shared Rice")
    bobs = await _make_food(db_session, "Bob's Shake", user_id=bob.id)
    client.set_user(alice)
    entry = (await client.post(
        "/api/nutrition/entries",
        json={"food_id": str(shared.id), "entry_date": "2026-06-13", "meal": "lunch"},
    )).json()

    resp = await client.patch(
        f"/api/nutrition/entries/{entry['id']}", json={"food_id": str(bobs.id)}
    )
    assert resp.status_code == 404  # Alice can't see Bob's private Food


async def test_update_diary_entry_can_move_meal(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    food = await _make_food(db_session, "Banana", serving_unit="medium", calories=105,
                            protein_g=1.3, carbs_g=27, fat_g=0.4)
    client.set_user(alice)
    entry = (await client.post(
        "/api/nutrition/entries",
        json={"food_id": str(food.id), "entry_date": "2026-06-13", "meal": "snack"},
    )).json()

    resp = await client.patch(
        f"/api/nutrition/entries/{entry['id']}", json={"meal": "breakfast"}
    )
    assert resp.status_code == 200
    assert resp.json()["meal"] == "breakfast"


async def test_delete_diary_entry(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    food = await _make_food(db_session, "Apple", serving_unit="medium", calories=95,
                            protein_g=0.5, carbs_g=25, fat_g=0.3)
    client.set_user(alice)
    entry = (await client.post(
        "/api/nutrition/entries",
        json={"food_id": str(food.id), "entry_date": "2026-06-13", "meal": "snack"},
    )).json()

    resp = await client.delete(f"/api/nutrition/entries/{entry['id']}")
    assert resp.status_code == 204
    # The day view no longer has it.
    day = (await client.get("/api/nutrition/diary", params={"date": "2026-06-13"})).json()
    assert day["total"]["calories"] == 0


# --------------------------------------------------------------------------- #
# Per-user scoping (security contract)
# --------------------------------------------------------------------------- #


async def test_user_cannot_read_or_mutate_another_users_entry(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    food = await _make_food(db_session, "Shared Rice")

    client.set_user(alice)
    entry = (await client.post(
        "/api/nutrition/entries",
        json={"food_id": str(food.id), "entry_date": "2026-06-13", "meal": "dinner"},
    )).json()

    # Bob can't edit or delete Alice's entry (404 — no leak of existence).
    client.set_user(bob)
    assert (await client.patch(f"/api/nutrition/entries/{entry['id']}", json={"quantity": 9})).status_code == 404
    assert (await client.delete(f"/api/nutrition/entries/{entry['id']}")).status_code == 404

    # And Bob's day view doesn't include Alice's entry.
    bob_day = (await client.get("/api/nutrition/diary", params={"date": "2026-06-13"})).json()
    assert bob_day["total"]["calories"] == 0

    # Alice's entry is untouched.
    client.set_user(alice)
    alice_day = (await client.get("/api/nutrition/diary", params={"date": "2026-06-13"})).json()
    assert alice_day["total"]["calories"] > 0


# --------------------------------------------------------------------------- #
# Day view: per-meal grouping + subtotals + day total
# --------------------------------------------------------------------------- #


async def test_diary_day_groups_by_meal_with_subtotals_and_total(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    egg = await _make_food(db_session, "Egg", serving_size=1, serving_unit="egg",
                           calories=72, protein_g=6.3, carbs_g=0.4, fat_g=4.8)
    banana = await _make_food(db_session, "Banana", serving_unit="medium",
                              calories=105, protein_g=1.3, carbs_g=27, fat_g=0.4)
    chicken = await _make_food(db_session, "Chicken")  # 165/31/0/3.6 per 100g
    client.set_user(alice)

    d = "2026-06-13"
    await client.post("/api/nutrition/entries", json={"food_id": str(egg.id), "entry_date": d, "meal": "breakfast", "quantity": 2})
    await client.post("/api/nutrition/entries", json={"food_id": str(banana.id), "entry_date": d, "meal": "breakfast", "quantity": 1})
    await client.post("/api/nutrition/entries", json={"food_id": str(chicken.id), "entry_date": d, "meal": "lunch", "quantity": 1.5})

    resp = await client.get("/api/nutrition/diary", params={"date": d})
    assert resp.status_code == 200
    day = resp.json()
    assert day["entry_date"] == d

    meals = {m["meal"]: m for m in day["meals"]}
    # All four meal slots are present (zeroed when empty).
    assert set(meals) == {"breakfast", "lunch", "dinner", "snack"}

    # Breakfast: 2 eggs (144 kcal) + 1 banana (105) = 249 kcal, 2 entries.
    assert len(meals["breakfast"]["entries"]) == 2
    assert meals["breakfast"]["totals"]["calories"] == 249
    assert meals["breakfast"]["totals"]["protein_g"] == pytest.approx(13.9)
    # Lunch: 1.5 * chicken = 247.5 kcal.
    assert meals["lunch"]["totals"]["calories"] == 247.5
    # Dinner + snack empty.
    assert meals["dinner"]["totals"]["calories"] == 0
    assert meals["snack"]["entries"] == []

    # Day total = 249 + 247.5 = 496.5
    assert day["total"]["calories"] == 496.5


async def test_diary_day_only_includes_that_day(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    food = await _make_food(db_session, "Rice")
    client.set_user(alice)
    await client.post("/api/nutrition/entries", json={"food_id": str(food.id), "entry_date": "2026-06-13", "meal": "lunch"})
    await client.post("/api/nutrition/entries", json={"food_id": str(food.id), "entry_date": "2026-06-12", "meal": "lunch"})

    day = (await client.get("/api/nutrition/diary", params={"date": "2026-06-13"})).json()
    total_entries = sum(len(m["entries"]) for m in day["meals"])
    assert total_entries == 1


async def test_diary_day_defaults_to_today(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    food = await _make_food(db_session, "Rice")
    client.set_user(alice)
    today = dt.date.today().isoformat()
    await client.post("/api/nutrition/entries", json={"food_id": str(food.id), "entry_date": today, "meal": "lunch"})

    # No ?date → today.
    resp = await client.get("/api/nutrition/diary")
    assert resp.status_code == 200
    assert resp.json()["entry_date"] == today
    assert resp.json()["total"]["calories"] > 0


# --------------------------------------------------------------------------- #
# History: per-day totals over a range
# --------------------------------------------------------------------------- #


async def test_history_returns_per_day_totals(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    chicken = await _make_food(db_session, "Chicken")  # 165 per 100g
    client.set_user(alice)

    await client.post("/api/nutrition/entries", json={"food_id": str(chicken.id), "entry_date": "2026-06-11", "meal": "lunch", "quantity": 1})
    await client.post("/api/nutrition/entries", json={"food_id": str(chicken.id), "entry_date": "2026-06-13", "meal": "lunch", "quantity": 2})

    resp = await client.get(
        "/api/nutrition/history", params={"start": "2026-06-10", "end": "2026-06-13"}
    )
    assert resp.status_code == 200
    by_date = {d["entry_date"]: d["total"]["calories"] for d in resp.json()}
    # Only days with entries appear, each with its own summed total.
    assert by_date == {"2026-06-11": 165, "2026-06-13": 330}


async def test_history_scoped_to_caller(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    food = await _make_food(db_session, "Rice")

    client.set_user(bob)
    await client.post("/api/nutrition/entries", json={"food_id": str(food.id), "entry_date": "2026-06-13", "meal": "lunch"})

    client.set_user(alice)
    resp = await client.get("/api/nutrition/history", params={"start": "2026-06-01", "end": "2026-06-30"})
    assert resp.status_code == 200
    assert resp.json() == []  # Alice has none; Bob's are not visible
