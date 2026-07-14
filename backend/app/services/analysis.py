"""LLM analysis layer (ADR-0011, plan M5) — qwen coach's notes + Proposals.

The narrate-and-propose seat. The digest the model sees is computed
DETERMINISTICALLY here (the LLM never touches raw tables); its output is
parsed defensively (schema-checked, reject-don't-guess), the narrative is
stored with the digest for audit, and every Proposal applies only after the
ENGINE validates it (clamped to the Principle band) and the user approves —
landing as a receipted Program revision (trigger=proposal). LLM down or
babbling ⇒ the numeric Block Review keeps adapting; only prose pauses.

Provider: the in-cluster llama-swap OpenAI-compatible endpoint (model
``qwen3-8b`` by default) — the same client shape as
:class:`app.services.adjust_agent.ClaudeAgentAdjustProvider`, with an
injectable httpx transport so tests never touch the network.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.analysis import AnalysisReport, Proposal, ProposalStatus
from app.models.program import Program, RevisionTrigger
from app.services.readiness_query import readiness_for_user
from app.services.review_query import (
    _bounds,
    _record_revision,
    _week_number,
    adherence_weeks,
)
from app.services.program_query import active_program

log = logging.getLogger("app.analysis")

#: Levers an LLM Proposal may use. Volume only in M5 — it has a crisp,
#: engine-ownable validation (the Principle band); rotations/structure stay
#: with the deterministic loops.
_ALLOWED_PROPOSAL_LEVERS = frozenset({"volume"})

_SYSTEM_PROMPT = (
    "You are the weekly training analyst for a strength app. You receive a "
    "JSON digest of one user's training week: per-muscle prescribed vs "
    "performed sets, hard failures (sets taken to 0 reps-in-reserve short of "
    "target), recent automatic program changes, and a readiness score. "
    "Respond with STRICT JSON only, no prose outside it, shaped exactly:\n"
    '{"narrative": "<3-6 plain sentences: what went well, what did not, what '
    'the engine changed and why it makes sense>", "proposals": [{"lever": '
    '"volume", "muscle": "<muscle>", "to": <int weekly sets>, "reason": '
    '"<one sentence>"}]}\n'
    "Propose at most 2 changes and only when the data clearly supports them; "
    "an empty proposals list is a good answer. Never invent muscles or data "
    "not present in the digest."
)


@dataclass(frozen=True)
class AnalysisResult:
    """A parsed provider response: the narrative + zero or more raw proposals."""

    narrative: str
    proposals: list[dict] = field(default_factory=list)


class AnalysisProvider(ABC):
    """Turns a weekly digest into coach's notes + structured Proposals."""

    @abstractmethod
    async def analyze(self, digest: dict) -> AnalysisResult | None:
        """None ⇒ the provider failed/was unusable (callers fail soft)."""
        raise NotImplementedError


class QwenAnalysisProvider(AnalysisProvider):
    """The in-cluster llama-swap (qwen3-8b) provider."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = (base_url or settings.ANALYSIS_LLM_URL).rstrip("/")
        self._model = model or settings.ANALYSIS_LLM_MODEL
        self._timeout = timeout_seconds
        self._transport = transport

    async def analyze(self, digest: dict) -> AnalysisResult | None:
        try:
            payload = {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(digest)},
                ],
                "temperature": 0.2,
                "max_tokens": 700,
            }
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                resp = await client.post(
                    f"{self._base_url}/v1/chat/completions", json=payload
                )
                resp.raise_for_status()
                content = str(
                    resp.json()["choices"][0]["message"]["content"]
                ).strip()
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            log.warning("analysis LLM call failed (%s)", type(exc).__name__)
            return None
        return parse_analysis_content(content)


def parse_analysis_content(content: str) -> AnalysisResult | None:
    """Schema-checked parse of the model output (reject-don't-guess).

    Tolerates a stray code fence; requires a non-empty string narrative;
    keeps only proposals with an allowed lever, a string muscle, an int
    target and a string reason — anything else is dropped (a malformed
    proposal costs itself, never the report).
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    narrative = data.get("narrative")
    if not isinstance(narrative, str) or not narrative.strip():
        return None
    proposals: list[dict] = []
    raw = data.get("proposals", [])
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            if item.get("lever") not in _ALLOWED_PROPOSAL_LEVERS:
                continue
            muscle = item.get("muscle")
            to = item.get("to")
            reason = item.get("reason", "")
            if not isinstance(muscle, str) or not isinstance(to, int):
                continue
            proposals.append(
                {
                    "lever": "volume",
                    "muscle": muscle,
                    "to": to,
                    "reason": str(reason),
                }
            )
    return AnalysisResult(narrative=narrative.strip(), proposals=proposals[:2])


async def build_weekly_digest(
    db: AsyncSession, user_id: int, program: Program, *, now: dt.datetime, week: int
) -> dict:
    """The deterministic digest the LLM is shown (also stored for audit)."""
    weeks = await adherence_weeks(db, user_id, now=now, weeks=4)
    target = next((w for w in weeks if w["week"] == week), None)
    readiness = await readiness_for_user(db, user_id, now=now)
    from app.models.program import ProgramRevision  # local import, avoids cycle

    recent_revisions = (
        (
            await db.execute(
                select(ProgramRevision)
                .where(ProgramRevision.program_id == program.id)
                .order_by(ProgramRevision.version.desc())
                .limit(3)
            )
        )
        .scalars()
        .all()
    )
    return {
        "week": week,
        "goal": str(program.goal),
        "days_per_week": program.days_per_week,
        "adherence": target or {"week": week, "sessions": 0, "muscles": []},
        "prior_weeks": [w for w in weeks if w["week"] < week][:2],
        "readiness_score": readiness.score,
        "recent_program_changes": [
            {"version": r.version, "trigger": r.trigger.value, "changes": r.changes}
            for r in recent_revisions
        ],
    }


async def run_weekly_analysis(
    db: AsyncSession,
    user_id: int,
    *,
    now: dt.datetime,
    provider: AnalysisProvider,
    force: bool = False,
) -> AnalysisReport | None:
    """Produce the coach's notes for the latest COMPLETE training week.

    Self-gating (the weekly cadence's idempotence): no active Program, no
    complete week yet, or a report already stored for that week ⇒ None.
    ``force`` regenerates the latest complete week's report in place (the
    on-demand "analyze now" button).
    """
    program = await active_program(db, user_id)
    if program is None:
        return None
    week = _week_number(program.created_at, now) - 1
    if week < 1:
        return None

    existing = (
        await db.execute(
            select(AnalysisReport).where(
                AnalysisReport.program_id == program.id,
                AnalysisReport.week == week,
            )
        )
    ).scalar_one_or_none()
    if existing is not None and not force:
        return None

    digest = await build_weekly_digest(db, user_id, program, now=now, week=week)
    result = await provider.analyze(digest)
    if result is None:
        return None

    if existing is not None:
        await db.delete(existing)
        await db.flush()
    report = AnalysisReport(
        user_id=user_id,
        program_id=program.id,
        week=week,
        narrative=result.narrative,
        digest=digest,
    )
    db.add(report)
    await db.flush()
    for raw in result.proposals:
        db.add(
            Proposal(
                user_id=user_id,
                program_id=program.id,
                report_id=report.id,
                change=raw,
            )
        )
    await db.flush()
    return report


class ProposalError(ValueError):
    """A proposal that can't be resolved/applied (gone, foreign, malformed)."""


async def resolve_proposal(
    db: AsyncSession,
    user_id: int,
    proposal_id: uuid.UUID,
    *,
    approve: bool,
    now: dt.datetime,
) -> Proposal:
    """Approve (validate → clamp → apply → receipt) or reject a Proposal.

    Approval is the ADR-0002 boundary in action: the stored suggestion is
    re-validated against the CURRENT Program (from-value re-derived, target
    clamped into the Principle band, future accumulation weeks only). A
    proposal whose muscle no longer exists in the ramp is rejected with an
    error rather than guessed at.
    """
    proposal = (
        await db.execute(
            select(Proposal).where(
                Proposal.id == proposal_id, Proposal.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if proposal is None:
        raise ProposalError("proposal not found")
    if proposal.status != ProposalStatus.pending:
        raise ProposalError("proposal already resolved")

    proposal.resolved_at = now
    if not approve:
        proposal.status = ProposalStatus.rejected
        await db.flush()
        return proposal

    program = await active_program(db, user_id)
    if program is None or program.id != proposal.program_id:
        raise ProposalError("the proposal's Program is no longer active")

    change = proposal.change or {}
    muscle = change.get("muscle")
    to = change.get("to")
    if change.get("lever") != "volume" or not isinstance(muscle, str) or not isinstance(to, int):
        raise ProposalError("unsupported proposal shape")

    current_week = _week_number(program.created_at, now)
    future = [
        v
        for v in program.muscle_volumes
        if v.muscle == muscle and v.week > current_week and not v.is_deload
    ]
    if not future:
        raise ProposalError(
            f"no future accumulation weeks for {muscle} — nothing to change"
        )
    lo, hi = (await _bounds(db, {muscle}))[muscle]
    clamped = max(lo, min(hi, to))
    from_value = min(future, key=lambda v: v.week).target_sets
    delta = clamped - from_value
    if delta != 0:
        for row in future:
            row.target_sets = max(1, row.target_sets + delta)

    receipt = [
        {
            "lever": "volume",
            "muscle": muscle,
            "from": from_value,
            "to": clamped,
            "reason": change.get("reason", "approved proposal"),
            "principle_key": "volume-dose-response",
            "proposal_id": str(proposal.id),
            "requested": to,
        }
    ]
    await _record_revision(db, program, receipt, trigger=RevisionTrigger.proposal)
    proposal.status = ProposalStatus.approved
    await db.flush()
    return proposal


def get_analysis_provider() -> AnalysisProvider:
    """The configured provider (qwen via llama-swap; the M5 default)."""
    return QwenAnalysisProvider()
