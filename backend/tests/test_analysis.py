"""LLM analysis layer (ADR-0011 M5): parse, gating, and the approval boundary.

- parse: strict-JSON schema check — reject garbage, tolerate fences, drop
  malformed/disallowed proposals without losing the report;
- run gating: no Program / no complete week / already-reported ⇒ None; a
  provider failure ⇒ None (fail soft, numbers keep adapting);
- approval: the engine re-derives from-values, CLAMPS the target into the
  Principle band, applies to future accumulation weeks only, and records a
  receipted revision (trigger=proposal); double-resolve conflicts.
The provider is exercised through a mocked httpx transport — no network.
"""

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.models.analysis import AnalysisReport, Proposal, ProposalStatus
from app.models.exercise import Muscle
from app.models.gym_profile import GymProfile
from app.models.program import ProgramRevision, RevisionTrigger
from app.models.user import User
from app.services.analysis import (
    AnalysisResult,
    AnalysisProvider,
    ProposalError,
    QwenAnalysisProvider,
    parse_analysis_content,
    resolve_proposal,
    run_weekly_analysis,
)

from tests.test_program_recommendation_api import _program
from tests.test_review_query import _prescribed_session
from tests.test_swap_exclusions_api import _exercise

NOW = datetime.now(timezone.utc)


async def _user(db, email="alice@example.com") -> User:
    u = User(email=email)
    db.add(u)
    await db.flush()
    return u


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_parse_accepts_valid_and_fenced_json() -> None:
    doc = {"narrative": "Good week.", "proposals": [
        {"lever": "volume", "muscle": "chest", "to": 14, "reason": "strong"}
    ]}
    plain = parse_analysis_content(json.dumps(doc))
    fenced = parse_analysis_content(f"```json\n{json.dumps(doc)}\n```")
    for result in (plain, fenced):
        assert result is not None
        assert result.narrative == "Good week."
        assert result.proposals == [
            {"lever": "volume", "muscle": "chest", "to": 14, "reason": "strong"}
        ]


def test_parse_rejects_garbage_and_missing_narrative() -> None:
    assert parse_analysis_content("the model rambles, no json") is None
    assert parse_analysis_content("[1,2,3]") is None
    assert parse_analysis_content('{"proposals": []}') is None
    assert parse_analysis_content('{"narrative": "  "}') is None


def test_parse_drops_malformed_or_disallowed_proposals_keeps_report() -> None:
    doc = {
        "narrative": "ok",
        "proposals": [
            {"lever": "split", "to": 4},  # disallowed lever
            {"lever": "volume", "muscle": "chest", "to": "12"},  # non-int
            {"lever": "volume", "muscle": "lats", "to": 15, "reason": "r"},
            {"lever": "volume", "muscle": "quads", "to": 12, "reason": "r"},
            {"lever": "volume", "muscle": "calves", "to": 11, "reason": "r"},
        ],
    }
    result = parse_analysis_content(json.dumps(doc))
    assert result is not None
    # Bad ones dropped; the rest capped at 2.
    assert [p["muscle"] for p in result.proposals] == ["lats", "quads"]


async def test_provider_via_mock_transport_and_failure_fail_soft() -> None:
    def ok_handler(request: httpx.Request) -> httpx.Response:
        body = {
            "choices": [
                {"message": {"content": json.dumps({"narrative": "n", "proposals": []})}}
            ]
        }
        return httpx.Response(200, json=body)

    provider = QwenAnalysisProvider(
        base_url="http://llm.test", transport=httpx.MockTransport(ok_handler)
    )
    result = await provider.analyze({"week": 1})
    assert result is not None and result.narrative == "n"

    def down_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    down = QwenAnalysisProvider(
        base_url="http://llm.test", transport=httpx.MockTransport(down_handler)
    )
    assert await down.analyze({"week": 1}) is None


# --------------------------------------------------------------------------- #
# Weekly run gating
# --------------------------------------------------------------------------- #


class _StubProvider(AnalysisProvider):
    def __init__(self, result: AnalysisResult | None):
        self.result = result
        self.calls = 0

    async def analyze(self, digest: dict) -> AnalysisResult | None:
        self.calls += 1
        return self.result


async def test_run_gates_and_persists_report_with_proposals(db_session) -> None:
    alice = await _user(db_session)
    provider = _StubProvider(
        AnalysisResult(
            narrative="Solid week.",
            proposals=[{"lever": "volume", "muscle": "chest", "to": 14, "reason": "r"}],
        )
    )
    # No active Program → None.
    assert await run_weekly_analysis(db_session, alice.id, now=NOW, provider=provider) is None

    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    db_session.add(GymProfile(user_id=alice.id, equipment=["barbell"]))
    fresh = await _program(
        db_session, alice, days=[("Push", [Muscle.chest])], created_at=NOW - timedelta(days=2)
    )
    # Program in week 1 → no COMPLETE week yet → None.
    assert await run_weekly_analysis(db_session, alice.id, now=NOW, provider=provider) is None
    assert provider.calls == 0

    # Age the Program into week 2 with a trained week 1.
    fresh.created_at = NOW - timedelta(weeks=1, days=1)
    await _prescribed_session(
        db_session,
        alice,
        fresh,
        started_at=fresh.created_at + timedelta(days=1),
        exercise=bench,
        muscle="chest",
        prescribed_sets=12,
        performed_sets=12,
    )
    report = await run_weekly_analysis(db_session, alice.id, now=NOW, provider=provider)
    assert report is not None
    assert report.week == 1
    assert report.narrative == "Solid week."
    assert report.digest["adherence"]["muscles"][0]["muscle"] == "chest"
    pending = (await db_session.execute(select(Proposal))).scalars().all()
    assert len(pending) == 1 and pending[0].status == ProposalStatus.pending

    # Same week again → gated (no duplicate), provider not re-called.
    calls = provider.calls
    assert await run_weekly_analysis(db_session, alice.id, now=NOW, provider=provider) is None
    assert provider.calls == calls

    # force=True regenerates in place (one report per week stays true).
    forced = await run_weekly_analysis(
        db_session, alice.id, now=NOW, provider=provider, force=True
    )
    assert forced is not None
    reports = (await db_session.execute(select(AnalysisReport))).scalars().all()
    assert len(reports) == 1


async def test_provider_failure_stores_nothing(db_session) -> None:
    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    program = await _program(
        db_session, alice, days=[("Push", [Muscle.chest])],
        created_at=NOW - timedelta(weeks=1, days=1),
    )
    await _prescribed_session(
        db_session, alice, program,
        started_at=program.created_at + timedelta(days=1),
        exercise=bench, muscle="chest", prescribed_sets=12, performed_sets=12,
    )
    assert (
        await run_weekly_analysis(
            db_session, alice.id, now=NOW, provider=_StubProvider(None)
        )
        is None
    )
    assert (await db_session.execute(select(AnalysisReport))).scalars().all() == []


# --------------------------------------------------------------------------- #
# The approval boundary
# --------------------------------------------------------------------------- #


async def test_approve_clamps_applies_and_receipts(db_session) -> None:
    alice = await _user(db_session)
    program = await _program(
        db_session, alice, days=[("Push", [Muscle.chest])],
        created_at=NOW - timedelta(weeks=1, days=1), volume_top=12,
    )
    # The LLM asks for an absurd 40 sets — the band (10..20) must clamp it.
    proposal = Proposal(
        user_id=alice.id,
        program_id=program.id,
        change={"lever": "volume", "muscle": "chest", "to": 40, "reason": "moar"},
    )
    db_session.add(proposal)
    await db_session.flush()

    resolved = await resolve_proposal(
        db_session, alice.id, proposal.id, approve=True, now=NOW
    )
    assert resolved.status == ProposalStatus.approved

    current_week = 2
    for row in program.muscle_volumes:
        if row.is_deload:
            continue
        assert row.target_sets == (20 if row.week > current_week else 12), f"wk {row.week}"
    assert program.version == 2
    rev = (await db_session.execute(select(ProgramRevision))).scalars().one()
    assert rev.trigger == RevisionTrigger.proposal
    assert rev.changes[0]["to"] == 20 and rev.changes[0]["requested"] == 40

    # Double-resolution conflicts.
    with pytest.raises(ProposalError):
        await resolve_proposal(db_session, alice.id, proposal.id, approve=True, now=NOW)


async def test_reject_keeps_the_record_and_touches_nothing(db_session) -> None:
    alice = await _user(db_session)
    program = await _program(
        db_session, alice, days=[("Push", [Muscle.chest])],
        created_at=NOW - timedelta(days=1), volume_top=12,
    )
    proposal = Proposal(
        user_id=alice.id,
        program_id=program.id,
        change={"lever": "volume", "muscle": "chest", "to": 14, "reason": "r"},
    )
    db_session.add(proposal)
    await db_session.flush()

    resolved = await resolve_proposal(
        db_session, alice.id, proposal.id, approve=False, now=NOW
    )
    assert resolved.status == ProposalStatus.rejected
    assert program.version == 1
    assert (await db_session.execute(select(ProgramRevision))).scalars().all() == []


async def test_weekly_set_series(db_session) -> None:
    from app.services.muscle_volume import weekly_set_series
    from app.models.training_session import TrainingSession, TrainingSet, SetType

    alice = await _user(db_session)
    bench = await _exercise(db_session, "Bench Press", [Muscle.chest])
    for days_ago, n in ((10, 3), (3, 5)):
        s = TrainingSession(user_id=alice.id, started_at=NOW - timedelta(days=days_ago))
        db_session.add(s)
        await db_session.flush()
        for i in range(n):
            db_session.add(
                TrainingSet(
                    session_id=s.id, exercise_id=bench.id, order_index=i,
                    weight_kg=60, reps=8, set_type=SetType.normal,
                )
            )
        # A warmup never counts.
        db_session.add(
            TrainingSet(
                session_id=s.id, exercise_id=bench.id, order_index=n,
                weight_kg=20, reps=10, set_type=SetType.warmup,
            )
        )
    await db_session.flush()
    series = await weekly_set_series(db_session, alice.id, now=NOW, weeks=4)
    assert sum(w["sets"] for w in series) == 8
    assert all(set(w) == {"week_start", "sets"} for w in series)
    assert series == sorted(series, key=lambda w: w["week_start"])
