"""Pydantic schemas for the Gym Profile endpoints.

The Gym Profile is a singleton per user: ``GET`` get-or-creates it (with sensible
defaults) and ``PUT`` replaces its fields wholesale (it's a small settings form,
not a partial-patch resource). Weights are in kilograms (the platform's canonical
unit); lists are normalized — sorted ascending and de-duplicated — on write so
the plate calculator gets clean input.
"""

from pydantic import BaseModel, Field, field_validator


def _clean_weights(values: list[float]) -> list[float]:
    """Drop non-positive weights, de-duplicate, and sort ascending."""
    return sorted({float(v) for v in values if v > 0})


class GymProfileUpdate(BaseModel):
    """Replace the caller's Gym Profile equipment (full-object PUT)."""

    bar_weights_kg: list[float] = Field(default_factory=list)
    plate_weights_kg: list[float] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

    @field_validator("bar_weights_kg", "plate_weights_kg")
    @classmethod
    def _normalize_weights(cls, v: list[float]) -> list[float]:
        return _clean_weights(v)

    @field_validator("equipment")
    @classmethod
    def _normalize_equipment(cls, v: list[str]) -> list[str]:
        # Trim, drop blanks, de-duplicate (case-insensitively), keep first-seen.
        seen: set[str] = set()
        out: list[str] = []
        for item in v:
            s = item.strip()
            key = s.lower()
            if s and key not in seen:
                seen.add(key)
                out.append(s)
        return out


class GymProfileRead(BaseModel):
    """The caller's Gym Profile as returned to the client."""

    bar_weights_kg: list[float] = []
    plate_weights_kg: list[float] = []
    equipment: list[str] = []

    model_config = {"from_attributes": True}
