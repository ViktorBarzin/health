"""Pydantic schemas for the Fitbod CSV import endpoints.

The import is a two-step, stateless flow: the client uploads the CSV text to
**preview** (parse + auto-match, no writes), resolves any unmatched names in the
UI, then submits the *same* CSV text plus its name→Exercise resolutions to
**commit**. Re-sending the text keeps the server stateless (no temp storage); the
import is idempotent so a resubmit is safe.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class FitbodPreviewRequest(BaseModel):
    """Upload a Fitbod CSV for a dry-run preview (no writes)."""

    csv_text: str = Field(min_length=1)
    model_config = {"extra": "forbid"}


class MatchedName(BaseModel):
    """A Fitbod exercise name that auto-resolved to a library Exercise."""

    fitbod_name: str
    exercise_id: uuid.UUID
    exercise_name: str


class UnresolvedName(BaseModel):
    """A Fitbod exercise name that needs the user to pick/create an Exercise."""

    fitbod_name: str
    # How many sets across the import carry this name (UI ordering / context).
    set_count: int


class FitbodPreviewResponse(BaseModel):
    """The dry-run summary the import UI renders before confirming."""

    session_count: int
    set_count: int
    skipped_rows: int
    matched: list[MatchedName]
    unresolved: list[UnresolvedName]


class FitbodCommitRequest(BaseModel):
    """Confirm a Fitbod import: the CSV text + the user's name resolutions.

    ``resolutions`` maps a raw Fitbod exercise name to the Exercise id the user
    chose (a library Exercise or a custom one they created in the flow). Names
    not present here fall back to the auto-matcher; names resolving to neither
    are skipped (reported in the result), never written as garbage Sets.
    """

    csv_text: str = Field(min_length=1)
    filename: str = Field(default="fitbod.csv", max_length=255)
    resolutions: dict[str, uuid.UUID] = Field(default_factory=dict)
    model_config = {"extra": "forbid"}


class FitbodImportResultResponse(BaseModel):
    """The outcome of a committed Fitbod import."""

    batch_id: uuid.UUID
    sessions_created: int
    sets_created: int
    unresolved_skipped: int
    skipped_rows: int
