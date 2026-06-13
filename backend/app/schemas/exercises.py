"""Pydantic schemas for the Exercise library endpoints."""

import uuid

from pydantic import BaseModel, Field, computed_field, field_validator

from app.models.exercise import Muscle, youtube_search_url


class ExerciseSummary(BaseModel):
    """List-view shape: enough to render a browse card.

    Validated straight off the ORM ``Exercise`` (``from_attributes``); the
    ``primary_muscles``/``secondary_muscles``/``is_custom`` fields read the
    model's properties of the same name.
    """

    id: uuid.UUID
    name: str
    category: str | None = None
    equipment: str | None = None
    level: str | None = None
    mechanic: str | None = None
    force: str | None = None
    primary_muscles: list[str] = []
    secondary_muscles: list[str] = []
    images: list[str] = []
    is_custom: bool = False

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def demo_video_url(self) -> str:
        return youtube_search_url(self.name)


class ExerciseDetail(ExerciseSummary):
    """Detail-view shape: adds instructions and the (already-present) media."""

    instructions: list[str] = []


class ExerciseCreate(BaseModel):
    """Payload to create a custom (private) Exercise.

    Muscle inputs are validated against the typed :class:`Muscle` enum so custom
    Exercises stay consistent with the shared catalog's analytics dimension.
    """

    name: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    equipment: str | None = Field(default=None, max_length=100)
    level: str | None = Field(default=None, max_length=50)
    mechanic: str | None = Field(default=None, max_length=50)
    force: str | None = Field(default=None, max_length=50)
    instructions: list[str] = []
    primary_muscles: list[Muscle] = []
    secondary_muscles: list[Muscle] = []

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class MuscleOption(BaseModel):
    """One selectable muscle for filter dropdowns / the create form."""

    value: str
    label: str


class RestPrefRead(BaseModel):
    """A user's rest-timer preference for one Exercise (#7).

    ``default_rest_seconds`` is the user's explicit override (NULL if unset);
    ``effective_rest_seconds`` is what the timer actually uses — the override or
    the app's global default — so the logger can start a countdown without
    second-guessing the fallback.
    """

    exercise_id: uuid.UUID
    default_rest_seconds: int | None = None
    effective_rest_seconds: int


class RestPrefUpdate(BaseModel):
    """Set (or clear) a user's rest default for an Exercise.

    ``null`` clears the override (the global default then applies); a value sets
    it. Bounded to a sane range — a rest timer of 0 or hours makes no sense.
    """

    default_rest_seconds: int | None = Field(default=None, ge=5, le=1800)
    model_config = {"extra": "forbid"}
