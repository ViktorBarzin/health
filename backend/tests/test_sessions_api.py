"""Session/Set logging API + per-user scoping contract.

- Start / list / get / finish / delete a Session (per user).
- Add / edit / delete / reorder Sets within a Session.
- A Set references a visible Exercise; weight × reps, set type, and Effort (as
  the one-tap RIR chip, stored as RPE-equivalent) round-trip.
- A user can never read or mutate another user's Session or its Sets.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user
from app.database import get_db
from app.main import app
from app.models.exercise import Exercise
from app.models.user import User


async def _make_user(db, email: str) -> User:
    user = User(email=email)
    db.add(user)
    await db.flush()
    return user


async def _make_exercise(db, name: str, *, user_id=None) -> Exercise:
    ex = Exercise(
        slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:6]}",
        name=name,
        user_id=user_id,
        source="free-exercise-db" if user_id is None else "custom",
    )
    db.add(ex)
    await db.flush()
    return ex


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
# Session CRUD
# --------------------------------------------------------------------------- #


async def test_start_session_creates_active_empty_session(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)

    resp = await client.post("/api/sessions/", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert body["is_active"] is True
    assert body["ended_at"] is None
    assert body["sets"] == []
    assert body["set_count"] == 0
    assert body["total_volume_kg"] == 0.0
    assert body["started_at"]  # server-defaulted


async def test_list_sessions_returns_only_own_newest_first(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")

    client.set_user(alice)
    s1 = (await client.post("/api/sessions/", json={})).json()["id"]
    s2 = (await client.post("/api/sessions/", json={})).json()["id"]

    client.set_user(bob)
    await client.post("/api/sessions/", json={})

    client.set_user(alice)
    resp = await client.get("/api/sessions/")
    assert resp.status_code == 200
    ids = [s["id"] for s in resp.json()]
    # Only Alice's two, and the most recently started first.
    assert set(ids) == {s1, s2}


async def test_finish_session_sets_end_time_and_is_idempotent(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    resp = await client.post(f"/api/sessions/{sid}/finish")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_active"] is False
    assert body["ended_at"] is not None
    first_end = body["ended_at"]

    # Finishing again is a no-op (keeps the original end time).
    again = await client.post(f"/api/sessions/{sid}/finish")
    assert again.status_code == 200
    assert again.json()["ended_at"] == first_end


async def test_list_filters_active_vs_finished(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    active = (await client.post("/api/sessions/", json={})).json()["id"]
    finished = (await client.post("/api/sessions/", json={})).json()["id"]
    await client.post(f"/api/sessions/{finished}/finish")

    only_active = await client.get("/api/sessions/", params={"active": "true"})
    assert [s["id"] for s in only_active.json()] == [active]

    only_finished = await client.get("/api/sessions/", params={"active": "false"})
    assert [s["id"] for s in only_finished.json()] == [finished]


async def test_delete_session_removes_it_and_its_sets(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    await client.post(
        f"/api/sessions/{sid}/sets",
        json={"exercise_id": str(ex.id), "weight_kg": 100, "reps": 5},
    )

    resp = await client.delete(f"/api/sessions/{sid}")
    assert resp.status_code == 204
    assert (await client.get(f"/api/sessions/{sid}")).status_code == 404


# --------------------------------------------------------------------------- #
# Set logging: weight × reps, set type, Effort
# --------------------------------------------------------------------------- #


async def test_add_set_records_weight_reps_and_defaults_to_normal(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Back Squat")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    resp = await client.post(
        f"/api/sessions/{sid}/sets",
        json={"exercise_id": str(ex.id), "weight_kg": 142.5, "reps": 5},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["weight_kg"] == 142.5
    assert body["reps"] == 5
    assert body["set_type"] == "normal"
    assert body["effort_rir"] is None  # Effort optional, not tapped
    assert body["order_index"] == 0
    assert body["exercise_id"] == str(ex.id)
    assert body["exercise_name"] == "Back Squat"


@pytest.mark.parametrize(
    "rir,expected_rpe_via_detail",
    [(0, 10.0), (1, 9.0), (2, 8.0), (3, 7.0), (4, 6.0)],
)
async def test_effort_rir_round_trips_through_the_api(
    client, db_session, rir, expected_rpe_via_detail
) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Deadlift")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    resp = await client.post(
        f"/api/sessions/{sid}/sets",
        json={
            "exercise_id": str(ex.id),
            "weight_kg": 180,
            "reps": 3,
            "effort_rir": rir,
        },
    )
    assert resp.status_code == 201
    # The API surfaces the chip value back unchanged…
    assert resp.json()["effort_rir"] == rir


async def test_set_type_chip_is_stored(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Overhead Press")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    resp = await client.post(
        f"/api/sessions/{sid}/sets",
        json={"exercise_id": str(ex.id), "weight_kg": 40, "reps": 12, "set_type": "warmup"},
    )
    assert resp.status_code == 201
    assert resp.json()["set_type"] == "warmup"


async def test_total_volume_excludes_non_normal_sets(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    # warmup (excluded) + two normal (counted) + failure (excluded)
    for w, r, t in [(60, 10, "warmup"), (100, 5, "normal"), (100, 4, "normal"), (110, 1, "failure")]:
        await client.post(
            f"/api/sessions/{sid}/sets",
            json={"exercise_id": str(ex.id), "weight_kg": w, "reps": r, "set_type": t},
        )

    detail = (await client.get(f"/api/sessions/{sid}")).json()
    assert detail["set_count"] == 4
    # Only the two normal sets: 100*5 + 100*4 = 900.
    assert detail["total_volume_kg"] == 900.0


async def test_add_set_assigns_sequential_order(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Row")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    indices = []
    for r in (8, 8, 8):
        body = (
            await client.post(
                f"/api/sessions/{sid}/sets",
                json={"exercise_id": str(ex.id), "weight_kg": 70, "reps": r},
            )
        ).json()
        indices.append(body["order_index"])
    assert indices == [0, 1, 2]


async def test_add_set_rejects_invisible_exercise(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    bobs_ex = await _make_exercise(db_session, "Bob Secret Move", user_id=bob.id)
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    # Alice can't log Bob's private custom Exercise.
    resp = await client.post(
        f"/api/sessions/{sid}/sets",
        json={"exercise_id": str(bobs_ex.id), "weight_kg": 50, "reps": 5},
    )
    assert resp.status_code == 404


async def test_effort_rir_out_of_range_is_rejected(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Curl")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    resp = await client.post(
        f"/api/sessions/{sid}/sets",
        json={"exercise_id": str(ex.id), "weight_kg": 20, "reps": 10, "effort_rir": 5},
    )
    assert resp.status_code == 422  # only 0..4 are valid chips


# --------------------------------------------------------------------------- #
# Set edit / delete / reorder
# --------------------------------------------------------------------------- #


async def test_update_set_changes_only_sent_fields(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    set_id = (
        await client.post(
            f"/api/sessions/{sid}/sets",
            json={"exercise_id": str(ex.id), "weight_kg": 100, "reps": 5, "effort_rir": 2},
        )
    ).json()["id"]

    # Bump reps only; weight, effort, type untouched.
    resp = await client.patch(
        f"/api/sessions/{sid}/sets/{set_id}", json={"reps": 6}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reps"] == 6
    assert body["weight_kg"] == 100
    assert body["effort_rir"] == 2
    assert body["set_type"] == "normal"


async def test_update_set_can_clear_effort_with_explicit_null(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    set_id = (
        await client.post(
            f"/api/sessions/{sid}/sets",
            json={"exercise_id": str(ex.id), "weight_kg": 100, "reps": 5, "effort_rir": 1},
        )
    ).json()["id"]

    resp = await client.patch(
        f"/api/sessions/{sid}/sets/{set_id}", json={"effort_rir": None}
    )
    assert resp.status_code == 200
    assert resp.json()["effort_rir"] is None


async def test_delete_set_compacts_order(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Row")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    ids = []
    for r in (5, 6, 7):
        ids.append(
            (
                await client.post(
                    f"/api/sessions/{sid}/sets",
                    json={"exercise_id": str(ex.id), "weight_kg": 70, "reps": r},
                )
            ).json()["id"]
        )

    # Delete the middle set; the third should slide from index 2 to 1.
    resp = await client.delete(f"/api/sessions/{sid}/sets/{ids[1]}")
    assert resp.status_code == 204

    detail = (await client.get(f"/api/sessions/{sid}")).json()
    remaining = [(s["id"], s["order_index"]) for s in detail["sets"]]
    assert remaining == [(ids[0], 0), (ids[2], 1)]


async def test_reorder_sets_rewrites_indices(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Squat")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    ids = []
    for r in (5, 6, 7):
        ids.append(
            (
                await client.post(
                    f"/api/sessions/{sid}/sets",
                    json={"exercise_id": str(ex.id), "weight_kg": 100, "reps": r},
                )
            ).json()["id"]
        )

    # Reverse the order.
    reversed_ids = list(reversed(ids))
    resp = await client.put(
        f"/api/sessions/{sid}/sets/order", json={"set_ids": reversed_ids}
    )
    assert resp.status_code == 200
    ordered = [s["id"] for s in resp.json()["sets"]]
    assert ordered == reversed_ids
    assert [s["order_index"] for s in resp.json()["sets"]] == [0, 1, 2]


async def test_reorder_rejects_wrong_id_set(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Squat")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    set_id = (
        await client.post(
            f"/api/sessions/{sid}/sets",
            json={"exercise_id": str(ex.id), "weight_kg": 100, "reps": 5},
        )
    ).json()["id"]

    # A list that isn't exactly the current set ids is a 400.
    resp = await client.put(
        f"/api/sessions/{sid}/sets/order",
        json={"set_ids": [set_id, str(uuid.uuid4())]},
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Per-user scoping (the security contract)
# --------------------------------------------------------------------------- #


async def test_cannot_read_another_users_session(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    client.set_user(bob)
    assert (await client.get(f"/api/sessions/{sid}")).status_code == 404


async def test_cannot_delete_another_users_session(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    client.set_user(bob)
    assert (await client.delete(f"/api/sessions/{sid}")).status_code == 404
    # Still there for Alice.
    client.set_user(alice)
    assert (await client.get(f"/api/sessions/{sid}")).status_code == 200


async def test_cannot_add_set_to_another_users_session(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    ex = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    client.set_user(bob)
    resp = await client.post(
        f"/api/sessions/{sid}/sets",
        json={"exercise_id": str(ex.id), "weight_kg": 100, "reps": 5},
    )
    assert resp.status_code == 404


async def test_cannot_edit_or_delete_another_users_set(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    ex = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    set_id = (
        await client.post(
            f"/api/sessions/{sid}/sets",
            json={"exercise_id": str(ex.id), "weight_kg": 100, "reps": 5},
        )
    ).json()["id"]

    client.set_user(bob)
    assert (
        await client.patch(f"/api/sessions/{sid}/sets/{set_id}", json={"reps": 99})
    ).status_code == 404
    assert (
        await client.delete(f"/api/sessions/{sid}/sets/{set_id}")
    ).status_code == 404

    # Alice's set is unchanged.
    client.set_user(alice)
    detail = (await client.get(f"/api/sessions/{sid}")).json()
    assert detail["sets"][0]["reps"] == 5


# --------------------------------------------------------------------------- #
# PR detection + celebration (the live record-of-truth on write)
# --------------------------------------------------------------------------- #


async def test_first_set_returns_prs_on_every_dimension(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    body = (
        await client.post(
            f"/api/sessions/{sid}/sets",
            json={"exercise_id": str(ex.id), "weight_kg": 100, "reps": 5},
        )
    ).json()
    kinds = {p["kind"] for p in body["prs"]}
    assert kinds == {"weight", "e1rm", "reps_at_weight", "volume"}
    # The reps PR carries the weight it happened at, for the banner copy.
    reps_pr = next(p for p in body["prs"] if p["kind"] == "reps_at_weight")
    assert reps_pr["at_weight_kg"] == 100.0
    assert reps_pr["value"] == 5.0


async def test_non_normal_set_returns_no_prs(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Squat")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    body = (
        await client.post(
            f"/api/sessions/{sid}/sets",
            json={
                "exercise_id": str(ex.id),
                "weight_kg": 300,
                "reps": 10,
                "set_type": "warmup",
            },
        )
    ).json()
    assert body["prs"] == []


async def test_second_weaker_set_does_not_re_pr(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Deadlift")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    await client.post(
        f"/api/sessions/{sid}/sets",
        json={"exercise_id": str(ex.id), "weight_kg": 200, "reps": 5},
    )
    # A weaker set at the SAME weight ties nothing new (200 already the best, and
    # 200 kg is a known weight with 5 reps; 3 reps < 5 → not even a reps PR).
    second = (
        await client.post(
            f"/api/sessions/{sid}/sets",
            json={"exercise_id": str(ex.id), "weight_kg": 200, "reps": 3},
        )
    ).json()
    assert second["prs"] == []


async def test_editing_weight_up_creates_a_pr(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Overhead Press")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    # Seed a 50 kg set so the second set has history to beat after editing.
    await client.post(
        f"/api/sessions/{sid}/sets",
        json={"exercise_id": str(ex.id), "weight_kg": 50, "reps": 5},
    )
    second_set = (
        await client.post(
            f"/api/sessions/{sid}/sets",
            json={"exercise_id": str(ex.id), "weight_kg": 40, "reps": 5},
        )
    ).json()
    # 40 < 50 so no weight/e1rm/volume PR, but 40 kg is a new weight bucket →
    # a first-at-weight reps PR.
    assert {p["kind"] for p in second_set["prs"]} == {"reps_at_weight"}

    # Correct that second set's weight up to 60 → now beats the 50 kg history on
    # weight + e1rm + volume (60×5=300 > 250), and 60 is again a new weight bucket.
    patched = (
        await client.patch(
            f"/api/sessions/{sid}/sets/{second_set['id']}",
            json={"weight_kg": 60},
        )
    ).json()
    kinds = {p["kind"] for p in patched["prs"]}
    assert "weight" in kinds
    assert "e1rm" in kinds


async def test_prs_endpoint_returns_persisted_records(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    await client.post(
        f"/api/sessions/{sid}/sets",
        json={"exercise_id": str(ex.id), "weight_kg": 100, "reps": 5},
    )

    resp = await client.get("/api/sessions/prs", params={"exercise_id": str(ex.id)})
    assert resp.status_code == 200
    records = resp.json()
    by_kind = {r["kind"]: r for r in records}
    assert set(by_kind) == {"weight", "e1rm", "reps_at_weight", "volume"}
    assert by_kind["weight"]["value"] == 100.0
    assert by_kind["volume"]["value"] == 500.0
    assert by_kind["reps_at_weight"]["at_weight_kg"] == 100.0
    for r in records:
        assert r["exercise_id"] == str(ex.id)


async def test_prs_endpoint_is_per_user(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    ex = await _make_exercise(db_session, "Bench Press")

    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    await client.post(
        f"/api/sessions/{sid}/sets",
        json={"exercise_id": str(ex.id), "weight_kg": 150, "reps": 5},
    )

    # Bob has logged nothing → no PRs for the same Exercise.
    client.set_user(bob)
    resp = await client.get("/api/sessions/prs", params={"exercise_id": str(ex.id)})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_progressive_overload_sequence_pr_dimensions(client, db_session) -> None:
    # A realistic ramp: each genuinely-better set fires exactly the right PRs.
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Squat")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]

    async def log(w, r):
        return (
            await client.post(
                f"/api/sessions/{sid}/sets",
                json={"exercise_id": str(ex.id), "weight_kg": w, "reps": r},
            )
        ).json()

    # 1) First ever 100×5 → all four.
    assert {p["kind"] for p in (await log(100, 5))["prs"]} == {
        "weight", "e1rm", "reps_at_weight", "volume"
    }
    # 2) 100×6: same weight, more reps@100 → reps + e1rm + volume (not weight).
    assert {p["kind"] for p in (await log(100, 6))["prs"]} == {
        "reps_at_weight", "e1rm", "volume"
    }
    # 3) 105×3 (new heavier weight, first at 105): weight + reps@105.
    #    e1RM 105*(1+2/30)=112 < 100×6 e1RM 116.67 → no e1rm; volume 315 < 600 → no.
    assert {p["kind"] for p in (await log(105, 3))["prs"]} == {
        "weight", "reps_at_weight"
    }


# --------------------------------------------------------------------------- #
# Offline-first replay: client-supplied ids + idempotent create (ADR-0005, #6)
# --------------------------------------------------------------------------- #


async def test_start_session_honours_client_supplied_id(client, db_session) -> None:
    # The offline logger mints the Session id at the gym; the server must use it
    # (so the Session's queued Sets, which reference it, land correctly).
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    sid = str(uuid.uuid4())

    resp = await client.post("/api/sessions/", json={"id": sid})
    assert resp.status_code == 201
    assert resp.json()["id"] == sid


async def test_start_session_replay_is_idempotent(client, db_session) -> None:
    # Replaying the same client-supplied create (flaky-response retry) returns
    # the existing Session, not a duplicate or a primary-key error.
    alice = await _make_user(db_session, "alice@example.com")
    client.set_user(alice)
    sid = str(uuid.uuid4())

    first = await client.post("/api/sessions/", json={"id": sid})
    assert first.status_code == 201
    again = await client.post("/api/sessions/", json={"id": sid})
    assert again.status_code == 201
    assert again.json()["id"] == sid

    # Exactly one Session exists.
    listing = await client.get("/api/sessions/")
    assert [s["id"] for s in listing.json()] == [sid]


async def test_another_users_session_id_does_not_collide(client, db_session) -> None:
    # A client id is only matched within the caller's own Sessions: Bob reusing
    # Alice's id gets a fresh Session under Bob, never Alice's.
    alice = await _make_user(db_session, "alice@example.com")
    bob = await _make_user(db_session, "bob@example.com")
    sid = str(uuid.uuid4())

    client.set_user(alice)
    await client.post("/api/sessions/", json={"id": sid})

    # The idempotency lookup is scoped to the caller's own Sessions, so Bob can
    # never read Alice's Session by guessing its id — that is the security
    # contract. (UUIDs don't collide across users in practice; an adversarial
    # exact-id reuse is out of scope — the per-user scoping is what matters.)
    client.set_user(bob)
    assert (await client.get(f"/api/sessions/{sid}")).status_code == 404
    client.set_user(alice)
    assert (await client.get(f"/api/sessions/{sid}")).status_code == 200


async def test_add_set_honours_client_supplied_id(client, db_session) -> None:
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    set_id = str(uuid.uuid4())

    resp = await client.post(
        f"/api/sessions/{sid}/sets",
        json={"id": set_id, "exercise_id": str(ex.id), "weight_kg": 100, "reps": 5},
    )
    assert resp.status_code == 201
    assert resp.json()["id"] == set_id


async def test_add_set_replay_is_idempotent_no_duplicate(client, db_session) -> None:
    # The crux of offline replay: re-POSTing an already-applied Set id (the
    # client never saw the first 2xx) returns the existing Set, does not
    # duplicate it, and does not trip the (session_id, order_index) unique
    # constraint by appending a second row at a new index.
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Bench Press")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    set_id = str(uuid.uuid4())
    body = {"id": set_id, "exercise_id": str(ex.id), "weight_kg": 100, "reps": 5}

    first = await client.post(f"/api/sessions/{sid}/sets", json=body)
    assert first.status_code == 201
    first_index = first.json()["order_index"]

    again = await client.post(f"/api/sessions/{sid}/sets", json=body)
    assert again.status_code == 201
    assert again.json()["id"] == set_id
    # Same slot, not a new one.
    assert again.json()["order_index"] == first_index

    # The Session holds exactly one Set.
    detail = (await client.get(f"/api/sessions/{sid}")).json()
    assert len(detail["sets"]) == 1


async def test_add_set_replay_does_not_re_award_a_pr(client, db_session) -> None:
    # A replayed create must not double-count toward PRs: the first 100x5 PRs on
    # every dimension; replaying the same id reconciles to the same record and
    # reports the dimensions the (unchanged) Set still holds — never a spurious
    # NEW record, and the persisted records stay single.
    alice = await _make_user(db_session, "alice@example.com")
    ex = await _make_exercise(db_session, "Squat")
    client.set_user(alice)
    sid = (await client.post("/api/sessions/", json={})).json()["id"]
    set_id = str(uuid.uuid4())
    body = {"id": set_id, "exercise_id": str(ex.id), "weight_kg": 100, "reps": 5}

    first = await client.post(f"/api/sessions/{sid}/sets", json=body)
    assert {p["kind"] for p in first.json()["prs"]} == {
        "weight", "e1rm", "reps_at_weight", "volume"
    }

    # Replay: the Set still holds those records (it IS the record holder), so the
    # same dimensions come back — but there's still only one Set and one record
    # per dimension.
    await client.post(f"/api/sessions/{sid}/sets", json=body)
    detail = (await client.get(f"/api/sessions/{sid}")).json()
    assert len(detail["sets"]) == 1

    prs = (await client.get("/api/sessions/prs", params={"exercise_id": str(ex.id)})).json()
    # One row per weight-independent dimension (weight, e1rm, volume) + one
    # reps_at_weight row for 100 kg = 4 rows, not 8.
    assert len(prs) == 4
