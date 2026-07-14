"""LLM analysis API (ADR-0011 M5) — /api/analysis.

Coach's notes + the Proposal approval queue. Reads are cheap DB fetches; the
on-demand run calls the LLM synchronously (seconds — the button shows a
spinner); approval routes through the engine's validation and lands as a
receipted revision. All per-user scoped.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.analysis import AnalysisReport, Proposal, ProposalStatus
from app.models.user import User
from app.services.analysis import (
    ProposalError,
    get_analysis_provider,
    resolve_proposal,
    run_weekly_analysis,
)
from app.services.program_query import active_program

router = APIRouter()


def _report_json(report: AnalysisReport) -> dict:
    return {
        "id": str(report.id),
        "week": report.week,
        "narrative": report.narrative,
        "created_at": report.created_at.isoformat(),
    }


def _proposal_json(p: Proposal) -> dict:
    return {
        "id": str(p.id),
        "change": p.change,
        "status": p.status.value,
        "created_at": p.created_at.isoformat(),
    }


@router.get("/report")
async def latest_report(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The newest coach's notes for the active Program (null when none yet)."""
    program = await active_program(db, user.id)
    if program is None:
        return {"report": None}
    report = (
        await db.execute(
            select(AnalysisReport)
            .where(AnalysisReport.program_id == program.id)
            .order_by(AnalysisReport.week.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {"report": _report_json(report) if report else None}


@router.post("/run")
async def run_now(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """On-demand analysis of the latest complete training week (regenerates)."""
    now = datetime.now(timezone.utc)
    report = await run_weekly_analysis(
        db, user.id, now=now, provider=get_analysis_provider(), force=True
    )
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Nothing to analyze yet (no complete training week on an active "
                "Program), or the analysis model is unavailable."
            ),
        )
    return {"report": _report_json(report)}


@router.get("/proposals")
async def pending_proposals(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """The caller's pending Proposals, newest first."""
    rows = (
        (
            await db.execute(
                select(Proposal)
                .where(
                    Proposal.user_id == user.id,
                    Proposal.status == ProposalStatus.pending,
                )
                .order_by(Proposal.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_proposal_json(p) for p in rows]


@router.post("/proposals/{proposal_id}/approve")
async def approve(
    proposal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Approve: engine-validate, clamp, apply as a receipted revision."""
    now = datetime.now(timezone.utc)
    try:
        proposal = await resolve_proposal(
            db, user.id, proposal_id, approve=True, now=now
        )
    except ProposalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _proposal_json(proposal)


@router.post("/proposals/{proposal_id}/reject")
async def reject(
    proposal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Reject a pending Proposal (kept, not deleted — rejections are signal)."""
    now = datetime.now(timezone.utc)
    try:
        proposal = await resolve_proposal(
            db, user.id, proposal_id, approve=False, now=now
        )
    except ProposalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return _proposal_json(proposal)
