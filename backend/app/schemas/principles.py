"""Pydantic schemas for the Principles knowledge base endpoints.

The wire shapes for the cited exercise-science rules the generator (#13) reads
and the receipts UI (#14) renders. :class:`ParamRange` is the typed contract over
one entry of a Principle's ``params`` JSONB — the generator validates a range
through it rather than poking the raw dict.
"""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, Field, computed_field, model_validator

from app.models.principle import (
    EvidenceGrade,
    ExperienceLevel,
    PrincipleCategory,
    TrainingGoal,
)


class ParamRange(BaseModel):
    """One typed parameter range inside a Principle's ``params``.

    A range may be bounded (``min``/``max``), a single ``value``, or carry just a
    ``unit`` — all optional so the same shape covers "10–20 sets", "≥2× per week"
    (min only), or "1.62 g/kg breakpoint" (value). At least one of the three must
    be present so a param entry is never empty. The generator reads ``min``/``max``
    to pick a number inside the evidence-backed window.
    """

    min: float | None = None
    max: float | None = None
    value: float | None = None
    unit: str | None = None

    @model_validator(mode="after")
    def _at_least_one_bound(self) -> "ParamRange":
        if self.min is None and self.max is None and self.value is None:
            raise ValueError("a param range needs at least one of min/max/value")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("param range min must be <= max")
        return self


class CitationRead(BaseModel):
    """A peer-reviewed source backing a Principle, with a resolvable link."""

    authors: str
    year: int
    title: str
    journal: str
    doi: str | None = None
    pmid: str | None = None
    url: str | None = None

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved_url(self) -> str | None:
        """Explicit URL, else a doi.org link, else a PubMed link."""
        if self.url:
            return self.url
        if self.doi:
            return f"https://doi.org/{self.doi}"
        if self.pmid:
            return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"
        return None


class PrincipleRead(BaseModel):
    """Full Principle shape: statement, params, applicability, grade, citations.

    Validated straight off the ORM ``Principle`` (``from_attributes``). ``params``
    is exposed as the raw typed dict (``{name: ParamRange}``) the generator reads.
    """

    id: uuid.UUID
    key: str
    statement: str
    category: PrincipleCategory
    params: dict[str, ParamRange] = {}
    goals: list[TrainingGoal] = []
    experience_levels: list[ExperienceLevel] = []
    evidence_grade: EvidenceGrade
    notes: str | None = None
    version: int
    updated_at: dt.datetime
    citations: list[CitationRead] = []

    model_config = {"from_attributes": True}


class CategoryOption(BaseModel):
    """One selectable Principle category, for filters."""

    value: str
    label: str
