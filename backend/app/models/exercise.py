"""Exercise library models.

The ``exercises`` table is the shared movement catalog the logger, importer, and
engine all reference (CONTEXT.md: "the Exercise library is shared across users").
A row with ``user_id IS NULL`` is a global/shared Exercise (seeded from
free-exercise-db); a row with a non-NULL ``user_id`` is that user's private custom
Exercise. A user's browse view is global ∪ their own.

Muscle mappings are stored normalized in ``exercise_muscles`` (one row per
muscle/role) rather than buried in JSON, so Recovery/analytics can ``GROUP BY``
muscle later. ``muscle`` and ``role`` are native Postgres enums — a typed
dimension, not free text.

Idempotent seeding keys on the natural key ``slug``: for global rows that is the
free-exercise-db dataset id (e.g. ``3_4_Sit-Up``); custom rows derive a slug from
their name. Two partial unique indexes enforce uniqueness separately for the
global namespace (``user_id IS NULL``) and each user's namespace, because
Postgres treats NULLs as distinct in a plain composite unique constraint.
"""

import enum
import uuid
from urllib.parse import quote_plus

from sqlalchemy import (
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Muscle(str, enum.Enum):
    """The muscle groups free-exercise-db tags (17 distinct values).

    A typed dimension so per-muscle volume/Recovery can ``GROUP BY`` it. Custom
    Exercises must pick from this set so analytics stay consistent across the
    shared catalog and user additions.
    """

    abdominals = "abdominals"
    abductors = "abductors"
    adductors = "adductors"
    biceps = "biceps"
    calves = "calves"
    chest = "chest"
    forearms = "forearms"
    glutes = "glutes"
    hamstrings = "hamstrings"
    lats = "lats"
    lower_back = "lower back"
    middle_back = "middle back"
    neck = "neck"
    quadriceps = "quadriceps"
    shoulders = "shoulders"
    traps = "traps"
    triceps = "triceps"


class MuscleRole(str, enum.Enum):
    """Whether a muscle is a primary mover or a secondary one for an Exercise."""

    primary = "primary"
    secondary = "secondary"


# SQLAlchemy Enum types. ``values_callable`` makes the stored DB labels the enum
# *values* (e.g. "lower back") rather than the member names ("lower_back").
# ``create_type`` defaults to True so metadata-driven ``create_all`` (used by the
# test suite) provisions the Postgres enum types; the Alembic migration creates
# them explicitly for real databases.
_MUSCLE_ENUM = SAEnum(
    Muscle,
    name="muscle",
    values_callable=lambda e: [m.value for m in e],
)
_ROLE_ENUM = SAEnum(
    MuscleRole,
    name="muscle_role",
    values_callable=lambda e: [m.value for m in e],
)


def youtube_search_url(name: str) -> str:
    """A deterministic external demo-video deep-link for an Exercise.

    No hosted video and no licensing: just a YouTube search for the movement's
    proper form, URL-encoded. Stable for a given name so it can be a computed
    property rather than a stored column.
    """
    return f"https://www.youtube.com/results?search_query={quote_plus(name + ' proper form')}"


class Exercise(Base):
    __tablename__ = "exercises"
    __table_args__ = (
        # Idempotency / natural-key uniqueness, split by namespace because a
        # plain UNIQUE(user_id, slug) would let duplicate global rows in (NULLs
        # compare distinct). Global library:
        Index(
            "uq_exercise_global_slug",
            "slug",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
        # Per-user custom namespace:
        Index(
            "uq_exercise_user_slug",
            "user_id",
            "slug",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        # Browse query: a user fetches global ∪ their own, so user_id is the
        # leading filter dimension.
        Index("ix_exercises_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # NULL = shared/global library Exercise; non-NULL = that user's custom one.
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    # Stable natural key: dataset id for global rows, name-derived for custom.
    slug: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # Looser dataset descriptors kept as text: the dataset has nulls, and custom
    # Exercises shouldn't be constrained to the dataset's exact vocabulary.
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    force: Mapped[str | None] = mapped_column(String, nullable=True)
    level: Mapped[str | None] = mapped_column(String, nullable=True)
    mechanic: Mapped[str | None] = mapped_column(String, nullable=True)
    equipment: Mapped[str | None] = mapped_column(String, nullable=True)
    instructions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    # Full CDN (jsDelivr) URLs — no image binaries are vendored into the repo.
    images: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Provenance: 'free-exercise-db' for seeded rows, 'custom' for user rows.
    source: Mapped[str] = mapped_column(
        String, nullable=False, server_default="custom"
    )

    muscles: Mapped[list["ExerciseMuscle"]] = relationship(
        back_populates="exercise",
        cascade="all, delete-orphan",
        order_by="ExerciseMuscle.id",
        lazy="selectin",
    )

    @property
    def demo_video_url(self) -> str:
        """Deterministic YouTube "proper form" search link for this Exercise."""
        return youtube_search_url(self.name)

    @property
    def is_custom(self) -> bool:
        """True for a user's private Exercise, False for the shared library."""
        return self.user_id is not None

    @property
    def primary_muscles(self) -> list[str]:
        return [
            m.muscle.value for m in self.muscles if m.role == MuscleRole.primary
        ]

    @property
    def secondary_muscles(self) -> list[str]:
        return [
            m.muscle.value for m in self.muscles if m.role == MuscleRole.secondary
        ]


class ExerciseMuscle(Base):
    """Normalized muscle mapping for an Exercise: one row per (muscle, role).

    A queryable, ``GROUP BY``-able dimension for Recovery/volume analytics.
    """

    __tablename__ = "exercise_muscles"
    __table_args__ = (
        # No (muscle, role) appears twice for one Exercise.
        Index(
            "uq_exercise_muscle",
            "exercise_id",
            "muscle",
            "role",
            unique=True,
        ),
        # Analytics: "all exercises hitting <muscle>" / GROUP BY muscle.
        Index("ix_exercise_muscles_muscle", "muscle"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exercises.id", ondelete="CASCADE"),
        nullable=False,
    )
    muscle: Mapped[Muscle] = mapped_column(_MUSCLE_ENUM, nullable=False)
    role: Mapped[MuscleRole] = mapped_column(_ROLE_ENUM, nullable=False)

    exercise: Mapped["Exercise"] = relationship(back_populates="muscles")
