"""Pydantic schemas for the Session/Set logging endpoints.

The API speaks **Effort as RIR** (the one-tap chip value 0–4, where 4 is the
"4+" bucket) — that is what the phone UI taps. RIR is mapped to its stored
RPE-equivalent on write and mapped back on read (see :mod:`app.services.effort`),
so the wire stays in the user's vocabulary while the column stays canonical.

``weight_kg`` is the platform's canonical unit (kilograms); reps are whole.
Effort and set_type are the only "extras" — per YAGNI there are deliberately no
per-set notes (cut and vindicated) and no set templates.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, computed_field, model_validator

from app.models.training_session import SetType
from app.services.effort import rpe_to_rir
from app.services.pr import PRKind


class SetCreate(BaseModel):
    """Log one Set into a Session. Appended at the end of the Session's order."""

    # Optional client-supplied id (ADR-0005 offline-first, #6). The offline
    # logger mints the Set UUID up front so a queued create replays idempotently
    # — re-POSTing an already-applied id returns the existing Set rather than
    # duplicating it. Omitted online → the server generates one as before.
    id: uuid.UUID | None = None
    exercise_id: uuid.UUID
    weight_kg: float = Field(ge=0, le=2000)
    reps: int = Field(ge=0, le=10000)
    # One-tap Effort: 0,1,2,3,4 (4 = the "4+" chip). Optional on every Set.
    effort_rir: int | None = Field(default=None, ge=0, le=4)
    set_type: SetType = SetType.normal
    # Superset grouping (#7): Sets sharing this per-Session integer are logged in
    # alternation. NULL/omitted = a standalone Set.
    superset_group: int | None = Field(default=None, ge=0)


class SetUpdate(BaseModel):
    """Edit an existing Set. Every field optional — only the sent ones change.

    ``effort_rir`` distinguishes "omitted" (leave Effort unchanged) from explicit
    ``null`` (clear it): a route checks whether the field was set rather than
    just whether it is ``None``.
    """

    weight_kg: float | None = Field(default=None, ge=0, le=2000)
    reps: int | None = Field(default=None, ge=0, le=10000)
    effort_rir: int | None = Field(default=None, ge=0, le=4)
    set_type: SetType | None = None
    # Superset grouping (#7). Like effort_rir, "omitted" leaves it unchanged while
    # explicit ``null`` clears it (the route checks whether the field was set).
    superset_group: int | None = Field(default=None, ge=0)

    model_config = {"extra": "forbid"}


class SetRead(BaseModel):
    """One Set as returned to the client, in the user's RIR vocabulary.

    Built from the ORM ``TrainingSet`` (``from_attributes``). The stored ``rpe``
    is presented back as ``effort_rir``; ``exercise_name`` is pulled from the
    loaded ``exercise`` relationship.
    """

    id: uuid.UUID
    exercise_id: uuid.UUID
    order_index: int
    weight_kg: float
    reps: int
    set_type: SetType
    # The stored RPE-equivalent, presented to the client as the RIR chip value.
    effort_rir: int | None = None
    # Superset grouping (#7): the per-Session group id, or NULL for standalone.
    superset_group: int | None = None
    exercise_name: str | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _from_orm(cls, data: object) -> object:
        """Derive RIR + exercise_name when validating off the ORM model."""
        # Only transform ORM instances; leave plain dicts (e.g. in tests) alone.
        if isinstance(data, dict):
            return data
        rpe = getattr(data, "rpe", None)
        exercise = getattr(data, "exercise", None)
        return {
            "id": data.id,
            "exercise_id": data.exercise_id,
            "order_index": data.order_index,
            "weight_kg": data.weight_kg,
            "reps": data.reps,
            "set_type": data.set_type,
            "effort_rir": rpe_to_rir(rpe),
            "superset_group": data.superset_group,
            "exercise_name": getattr(exercise, "name", None),
        }


class PRReadout(BaseModel):
    """One personal record a written Set achieved, for the live celebration.

    Mirrors :class:`app.services.pr.PRResult`. ``kind`` is the dimension; ``value``
    is the new record (kg / estimated kg / reps / kg·reps depending on kind);
    ``at_weight_kg`` is the weight a reps-at-weight PR was set at, else ``None``.
    The frontend phrases the banner from these ("New 5-rep PR — 100 kg!").
    """

    kind: PRKind
    value: float
    at_weight_kg: float | None = None


class SetWriteResult(SetRead):
    """A written (added/edited) Set plus any PRs it set.

    Extends :class:`SetRead` so the client still gets the full Set back; ``prs`` is
    empty unless the write beat the user's history on one or more dimensions. The
    detection is server-authoritative — the offline client celebrates immediately
    from its own mirror of the algorithm, and this reconciles it on sync.
    """

    prs: list[PRReadout] = []


class PersonalRecordRead(BaseModel):
    """A persisted personal record row, as returned by the PR query endpoint.

    The authoritative current best on one dimension for an Exercise. ``at_weight_kg``
    is set only for the reps-at-weight kind. ``achieved_at`` lets the client sort
    or surface "set on <date>".
    """

    exercise_id: uuid.UUID
    kind: PRKind
    value: float
    at_weight_kg: float | None = None
    achieved_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _from_orm(cls, data: object) -> object:
        """Map the ORM ``weight_bucket`` column onto the wire ``at_weight_kg``."""
        if isinstance(data, dict):
            return data
        return {
            "exercise_id": data.exercise_id,
            "kind": data.kind,
            "value": data.value,
            "at_weight_kg": data.weight_bucket,
            "achieved_at": data.achieved_at,
        }


class SessionCreate(BaseModel):
    """Start a Session. ``started_at`` defaults to now() server-side if omitted."""

    # Optional client-supplied id (ADR-0005 offline-first, #6). A Session started
    # at the gym with no signal mints its UUID locally so its Sets can reference
    # it and the queued create replays idempotently (re-POSTing the same id
    # returns the existing Session). Omitted online → the server generates one.
    id: uuid.UUID | None = None
    started_at: datetime | None = None
    model_config = {"extra": "forbid"}


class SessionSummary(BaseModel):
    """List-view shape for a Session: timing plus derived counts and volume.

    ``set_count`` and ``total_volume_kg`` are computed by the route (the latter
    via :func:`app.services.volume.session_volume`, which already excludes
    non-normal Sets).
    """

    id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None = None
    set_count: int = 0
    total_volume_kg: float = 0.0

    model_config = {"from_attributes": True}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_active(self) -> bool:
        """True while the Session is still being logged (no end time yet)."""
        return self.ended_at is None


class SessionDetail(SessionSummary):
    """Detail-view shape: the Session plus its Sets in order."""

    sets: list[SetRead] = []


class SetReorder(BaseModel):
    """Reorder a Session's Sets: the full list of Set ids in the desired order."""

    set_ids: list[uuid.UUID] = Field(min_length=1)


class SupersetGroupRequest(BaseModel):
    """Group the given Sets into one Superset (a fresh group id is assigned).

    The Sets must span at least two distinct Exercises (a Superset is two or more
    Exercises in alternation — CONTEXT.md); the route validates that.
    """

    set_ids: list[uuid.UUID] = Field(min_length=2)
    model_config = {"extra": "forbid"}
