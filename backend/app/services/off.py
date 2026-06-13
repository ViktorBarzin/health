"""Open Food Facts integration — barcode → packaged Food (#22).

A scanned barcode resolves to a packaged **Food** via the Open Food Facts (OFF)
public API. This module has two layers:

* :func:`map_off_product` — the **pure** mapping (no network, no DB): one OFF v2
  ``product`` payload → a :class:`MappedFood` value object, or :class:`OffMappingError`
  when the macros are missing/garbage. OFF reports macros **per 100 g**
  (``energy-kcal_100g`` / ``proteins_100g`` / ``carbohydrates_100g`` / ``fat_100g``),
  so we store the Food with a **100 g serving** and the per-100g values as its
  per-serving macros — no fragile parse of OFF's free-text ``serving_size`` and no
  unit guesswork. A Diary Entry then scales by quantity (number of 100 g servings)
  exactly like every other Food.
* :func:`lookup_barcode` (in :mod:`app.services.off_lookup`) — the cache + fetch
  layer that persists the mapped product as a shared ``source='off'`` Food so a
  repeat scan is instant and offline-ish. Kept in a separate module so this one
  stays import-light and trivially unit-testable.

Honesty rule (mirrors the Fitbod parser's "skip, don't fabricate"): if OFF is
missing the energy or **any** of the three macros, or a value isn't a
non-negative number, we **reject** rather than defaulting to zero — a Food with
fake macros is worse than no Food (the caller falls back to manual entry).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Provenance marker for an OFF-cached Food (matches Food.source / the seed's
# 'generic' / a custom Food's 'custom').
OFF_SOURCE = "off"
# OFF macros are per 100 g; the cached Food uses a 100 g serving so its
# per-serving macros ARE the per-100g values.
_SERVING_SIZE_G = 100.0
_SERVING_UNIT = "g"


class OffMappingError(ValueError):
    """Raised when an OFF product can't be mapped to an honest Food.

    The caller treats this as "not usable" — a 404 to the client, which falls
    back to manual entry. Never write a Food with fabricated/zero macros.
    """


@dataclass(frozen=True)
class MappedFood:
    """The fields of a shared ``source='off'`` Food mapped from an OFF product.

    A pure value object (no ORM): the cache layer turns it into a ``Food`` row.
    """

    off_id: str
    slug: str
    name: str
    brand: str | None
    serving_size: float
    serving_unit: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    source: str = OFF_SOURCE


def off_slug(barcode: str) -> str:
    """The stable natural key for an OFF-cached Food: namespaced by barcode.

    Deterministic from the barcode so two resolutions of the same product land on
    the same shared-catalog row (``uq_food_global_slug``).
    """
    return f"off-{barcode}"


def _coerce_macro(value: object) -> float | None:
    """Parse an OFF nutriment into a non-negative float, or None if unusable.

    OFF usually sends numbers but occasionally strings; accept either. Reject
    anything that isn't a finite, non-negative number (negatives are corrupt
    data, not a real macro).
    """
    if isinstance(value, bool):  # bool is an int subclass — never a macro
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    elif isinstance(value, str):
        try:
            num = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if num != num or num in (float("inf"), float("-inf")):  # NaN / inf
        return None
    if num < 0:
        return None
    return num


def map_off_product(barcode: str, product: dict) -> MappedFood:
    """Map one OFF v2 ``product`` payload to a :class:`MappedFood` (per 100 g).

    Raises :class:`OffMappingError` if energy or any of protein/carbs/fat is
    missing or not a non-negative number — we never store a Food with fabricated
    macros.
    """
    nutriments = product.get("nutriments") or {}
    if not isinstance(nutriments, dict):
        raise OffMappingError("OFF product has no nutriments")

    calories = _coerce_macro(nutriments.get("energy-kcal_100g"))
    protein = _coerce_macro(nutriments.get("proteins_100g"))
    carbs = _coerce_macro(nutriments.get("carbohydrates_100g"))
    fat = _coerce_macro(nutriments.get("fat_100g"))

    missing = [
        label
        for label, val in (
            ("energy-kcal", calories),
            ("proteins", protein),
            ("carbohydrates", carbs),
            ("fat", fat),
        )
        if val is None
    ]
    if missing:
        raise OffMappingError(
            f"OFF product {barcode} missing usable macros: {', '.join(missing)}"
        )

    name = _clean(product.get("product_name")) or f"Product {barcode}"
    brand = _first_brand(product.get("brands"))

    return MappedFood(
        off_id=barcode,
        slug=off_slug(barcode),
        name=name,
        brand=brand,
        serving_size=_SERVING_SIZE_G,
        serving_unit=_SERVING_UNIT,
        calories=calories,  # type: ignore[arg-type]  (None ruled out above)
        protein_g=protein,  # type: ignore[arg-type]
        carbs_g=carbs,  # type: ignore[arg-type]
        fat_g=fat,  # type: ignore[arg-type]
    )


def _clean(value: object) -> str:
    """Trim a possibly-missing OFF string field to a clean str ('' if absent)."""
    return value.strip() if isinstance(value, str) else ""


def _first_brand(value: object) -> str | None:
    """OFF ``brands`` is a comma-separated list; take the first, or None."""
    cleaned = _clean(value)
    if not cleaned:
        return None
    first = cleaned.split(",")[0].strip()
    return first or None


# A retail barcode is digits only (EAN-8/EAN-13/UPC-A/UPC-E). Used by the API to
# reject obvious junk before a network round-trip.
_BARCODE_RE = re.compile(r"^\d{6,14}$")


def is_valid_barcode(code: str) -> bool:
    """True for a plausible retail barcode (6–14 digits), False otherwise."""
    return bool(_BARCODE_RE.match(code))
