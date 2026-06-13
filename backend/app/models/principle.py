"""Principles knowledge base — versioned, cited exercise-science rules.

CONTEXT.md ("Principle"): "A versioned rule in the exercise-science knowledge
base — statement, parameter ranges, applicability, evidence grade, and
peer-reviewed citations — from which every Program and Recommendation parameter
derives." ADR-0004 makes this the *sole* source the deterministic generator
(#13) composes from, so every prescribed training parameter is traceable to a
study; the receipts UI (#14) taps a Principle to show "why this number".

Shape decisions
===============
* **One row per rule, keyed on a stable ``key`` slug** (e.g. ``volume-dose-
  response``) — the natural key the generator and UI look a Principle up by, and
  the upsert key for the idempotent seed (mirroring how the Exercise seed keys on
  ``slug``).
* **``params`` is a JSONB dict of typed parameter objects** — the structured
  ranges the generator reads. Each entry is ``{min?, max?, unit?, value?}`` keyed
  by parameter name, e.g.::

      {"sets_per_muscle_per_week": {"min": 10, "max": 20, "unit": "sets"}}

  A dict-of-typed-params (rather than rigid min/max columns) lets one Principle
  carry several named ranges and lets the generator fetch a range by name. JSONB
  matches the repo's existing convention for small read-whole/write-whole
  structures (Gym Profile lists, Exercise instructions/images). The
  :class:`ParamRange` Pydantic schema is the typed contract over an entry.
* **Applicability is two JSONB string arrays** — ``goals`` (which
  :class:`TrainingGoal` values the rule applies to) and ``experience_levels``
  (which :class:`ExperienceLevel` values). A rule applies to a *set* of each;
  storing the enum *values* (not a join table) keeps the KB a flat, seed-authored
  document and lets the query layer filter with a simple JSONB-contains. Empty/
  absent ⇒ "applies to all" (a universal Principle like progressive overload).
* **``evidence_grade``** is a native enum (A/B/C = strong/moderate/limited) so the
  UI and any future weighting can treat it as a typed dimension.
* **Versioned** via an integer ``version`` plus ``updated_at`` — the rules evolve
  as the literature does; a re-seed bumps fields in place and the version lets a
  consumer detect a change.

Citations live in the normalized child table :class:`PrincipleCitation` (one row
per source — authors/year/title/journal/DOI/PMID/URL), the same normalized shape
``exercise_muscles`` uses, so a Principle can carry several verified citations and
the UI can render each as a real reference with a resolvable link.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TrainingGoal(str, enum.Enum):
    """The user's training intent (CONTEXT.md "Goal").

    The canonical home for the Goal vocabulary the Program generator (#13) and
    Budget (#15) consume — a Principle's applicability is expressed in these.
    """

    bulk = "bulk"
    cut = "cut"
    maintain = "maintain"
    strength = "strength"


class ExperienceLevel(str, enum.Enum):
    """Training experience tier a Principle's parameters apply to.

    Mirrors the free-exercise-db ``level`` vocabulary (beginner/intermediate/
    advanced) so the guided quiz's experience answer maps straight onto it.
    """

    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class PrincipleCategory(str, enum.Enum):
    """The training dimension a Principle governs (ADR-0004 examples)."""

    volume = "volume"
    frequency = "frequency"
    intensity = "intensity"  # effort / proximity-to-failure
    progression = "progression"
    periodization = "periodization"
    deload = "deload"
    rest = "rest"
    nutrition = "nutrition"  # protein / energy


class EvidenceGrade(str, enum.Enum):
    """How strong the evidence behind a Principle is.

    A = strong (multiple meta-analyses / position stands), B = moderate (a sound
    RCT or meta-analysis with caveats), C = limited (indirect, consensus, or
    qualitative evidence). The receipts UI surfaces this so the user can weigh a
    number's confidence.
    """

    A = "A"
    B = "B"
    C = "C"


# ``values_callable`` stores the enum *values* as the DB labels (matching the
# Exercise enums' convention). ``create_type`` defaults True so metadata-driven
# ``create_all`` (the test suite) provisions the types; the Alembic migration
# creates them explicitly for real databases.
_GOAL_ENUM = SAEnum(
    TrainingGoal, name="training_goal", values_callable=lambda e: [m.value for m in e]
)
_LEVEL_ENUM = SAEnum(
    ExperienceLevel,
    name="experience_level",
    values_callable=lambda e: [m.value for m in e],
)
_CATEGORY_ENUM = SAEnum(
    PrincipleCategory,
    name="principle_category",
    values_callable=lambda e: [m.value for m in e],
)
_GRADE_ENUM = SAEnum(
    EvidenceGrade, name="evidence_grade", values_callable=lambda e: [m.value for m in e]
)


class Principle(Base):
    """One versioned, cited exercise-science rule the generator composes from."""

    __tablename__ = "principles"
    __table_args__ = (
        # ``key`` is the stable natural key the generator/UI look up by and the
        # seed upserts on — unique across the (global, single-namespace) KB.
        Index("uq_principle_key", "key", unique=True),
        # The query layer fetches by category for the receipts UI / browse.
        Index("ix_principles_category", "category"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Stable slug, e.g. "volume-dose-response".
    key: Mapped[str] = mapped_column(String, nullable=False)
    # Human-readable rule statement (plain English, shown in the receipts UI).
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[PrincipleCategory] = mapped_column(_CATEGORY_ENUM, nullable=False)
    # Typed parameter ranges the generator reads, keyed by name; see ParamRange.
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # Applicability: the Goal/experience sets this rule applies to. Empty ⇒ all.
    goals: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    experience_levels: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    evidence_grade: Mapped[EvidenceGrade] = mapped_column(_GRADE_ENUM, nullable=False)
    # Optional authoring note (e.g. a caveat on a weaker citation).
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Versioning: bumped when the rule's substance changes; updated_at is touched
    # on every write by the DB.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    citations: Mapped[list["PrincipleCitation"]] = relationship(
        back_populates="principle",
        cascade="all, delete-orphan",
        order_by="PrincipleCitation.id",
        lazy="selectin",
    )

    def applies_to(
        self,
        goal: TrainingGoal | str | None = None,
        experience: ExperienceLevel | str | None = None,
    ) -> bool:
        """Whether this Principle applies to a ``(goal, experience)`` context.

        An empty applicability list means "applies to every value of that
        dimension" (a universal rule). A given ``goal``/``experience`` matches
        when the list is empty or contains its value; ``None`` skips that
        dimension. This is the single source of the applicability rule — the
        query layer filters in SQL for efficiency but agrees with this.
        """
        goal_value = goal.value if isinstance(goal, TrainingGoal) else goal
        exp_value = (
            experience.value
            if isinstance(experience, ExperienceLevel)
            else experience
        )
        if goal_value is not None and self.goals and goal_value not in self.goals:
            return False
        if (
            exp_value is not None
            and self.experience_levels
            and exp_value not in self.experience_levels
        ):
            return False
        return True


class PrincipleCitation(Base):
    """One peer-reviewed source backing a Principle (normalized child row).

    Each carries enough to render a real reference and resolve it: ``authors``
    (free text, "Surname et al."), ``year``, ``title``, ``journal``, and at least
    one resolvable identifier — ``doi`` and/or ``pmid`` (and an optional ``url``).
    Verified against the primary literature at seed-authoring time (ADR-0004).
    """

    __tablename__ = "principle_citations"
    __table_args__ = (
        # No exact-duplicate citation under one Principle (keyed by source title).
        Index("uq_principle_citation", "principle_id", "title", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    principle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("principles.id", ondelete="CASCADE"),
        nullable=False,
    )
    authors: Mapped[str] = mapped_column(String, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    journal: Mapped[str] = mapped_column(String, nullable=False)
    # At least one of doi/pmid is set (a resolvable identifier); url optional.
    doi: Mapped[str | None] = mapped_column(String, nullable=True)
    pmid: Mapped[str | None] = mapped_column(String, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)

    principle: Mapped["Principle"] = relationship(back_populates="citations")

    @property
    def resolved_url(self) -> str | None:
        """A resolvable link for this citation: explicit URL, else DOI, else PMID."""
        if self.url:
            return self.url
        if self.doi:
            return f"https://doi.org/{self.doi}"
        if self.pmid:
            return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"
        return None
