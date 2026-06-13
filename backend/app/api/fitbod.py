"""Fitbod CSV import API — preview then commit, per user.

Mounted under ``/api/import`` alongside the Apple Health uploader. The flow is
stateless and two-step (see :mod:`app.schemas.fitbod`):

* ``POST /api/import/fitbod/preview`` — parse + auto-match the uploaded CSV text,
  return a summary + the unmatched names for the manual-match UI. No writes.
* ``POST /api/import/fitbod/commit`` — write Sessions/Sets idempotently using the
  user's name resolutions; re-running adds only what's missing.

Everything is scoped to ``get_current_user`` — imported data is attributed to the
caller and a Fitbod Source. The CSV is small (a workout history is KBs), so it
travels as JSON text rather than the chunked-multipart path the multi-GB Apple
Health export uses.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.exercise import Exercise
from app.models.user import User
from app.schemas.fitbod import (
    FitbodCommitRequest,
    FitbodImportResultResponse,
    FitbodPreviewRequest,
    FitbodPreviewResponse,
    MatchedName,
    UnresolvedName,
)
from app.services.fitbod_import import (
    commit_fitbod_import,
    preview_fitbod_import,
)
from app.services.fitbod_parser import FitbodParseError

router = APIRouter()


@router.post("/fitbod/preview", response_model=FitbodPreviewResponse)
async def preview_fitbod(
    payload: FitbodPreviewRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FitbodPreviewResponse:
    """Dry-run a Fitbod CSV: parse, auto-match, and report unmatched names."""
    try:
        preview = await preview_fitbod_import(
            db, user=user, csv_text=payload.csv_text
        )
    except FitbodParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    # Resolve matched-exercise display names in one query for the summary table.
    matched_ids = list(preview.matched_names.values())
    names_by_id: dict = {}
    if matched_ids:
        rows = (
            await db.execute(
                select(Exercise.id, Exercise.name).where(
                    Exercise.id.in_(matched_ids)
                )
            )
        ).all()
        names_by_id = {r[0]: r[1] for r in rows}

    matched = [
        MatchedName(
            fitbod_name=name,
            exercise_id=ex_id,
            exercise_name=names_by_id.get(ex_id, ""),
        )
        for name, ex_id in sorted(preview.matched_names.items())
    ]

    # Per-name set counts give the UI useful context ("Mystery Machine — 6 sets").
    unresolved = [
        UnresolvedName(
            fitbod_name=name, set_count=preview.set_counts.get(name, 0)
        )
        for name in preview.unresolved_names
    ]

    return FitbodPreviewResponse(
        session_count=preview.session_count,
        set_count=preview.set_count,
        skipped_rows=preview.skipped_rows,
        matched=matched,
        unresolved=unresolved,
    )


@router.post(
    "/fitbod/commit",
    response_model=FitbodImportResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def commit_fitbod(
    payload: FitbodCommitRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FitbodImportResultResponse:
    """Commit a Fitbod import idempotently with the user's name resolutions."""
    try:
        result = await commit_fitbod_import(
            db,
            user=user,
            csv_text=payload.csv_text,
            filename=payload.filename,
            resolutions=payload.resolutions,
        )
    except FitbodParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await db.commit()
    return FitbodImportResultResponse(
        batch_id=result.batch_id,
        sessions_created=result.sessions_created,
        sets_created=result.sets_created,
        unresolved_skipped=result.unresolved_skipped,
        skipped_rows=result.skipped_rows,
    )
