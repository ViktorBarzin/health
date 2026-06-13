"""OFF barcode lookup with a shared local cache (#22).

A scanned barcode resolves to a packaged Food. :func:`lookup_barcode` is the
server-side cache+fetch layer (the pure mapping lives in :mod:`app.services.off`):

1. **Cache first** — return the existing shared ``source='off'`` Food for this
   barcode if we've resolved it before. Repeat scans/logs are then instant and
   work offline-ish (no network), and a re-scan hits the cache, not the network.
2. **Fetch on miss** — call the OFF v2 public product API with a proper
   ``User-Agent`` (OFF asks every client to identify itself), restricting the
   response to the fields we map. The HTTP client is injectable (``transport``)
   so tests mock it and never hit the network.
3. **Map + persist** — map the product with :func:`app.services.off.map_off_product`
   and persist it as a **shared** Food (``user_id IS NULL``) so every user reuses
   the same cache row. A concurrent first-scan race is handled by catching the
   unique-violation on ``uq_food_global_slug`` and re-selecting the winner.
4. **Fail soft** — a not-found product (OFF ``status: 0``), incomplete/garbage
   macros (:class:`OffMappingError`), or any network/HTTP error returns ``None``
   and writes nothing; the API turns that into a 404 and the client falls back to
   manual entry. We never write a Food with fabricated macros.

The OFF call is done server-side (not from the browser) so the cache is shared
across users and the User-Agent / CORS are controlled — the same rationale as the
claude-agent call in :mod:`app.services.adjust_agent`.
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.food import Food
from app.services.off import (
    OFF_SOURCE,
    MappedFood,
    OffMappingError,
    map_off_product,
    off_slug,
)

log = logging.getLogger(__name__)

# OFF public product endpoint. ``fields`` trims the (often huge) payload to just
# what we map. ``world`` is the multi-lingual aggregate (no key, public).
_OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
_OFF_FIELDS = "code,product_name,brands,nutriments"
# OFF asks every client to identify itself with a descriptive User-Agent so it can
# contact us / avoid blocking. (Self-hosted fitness platform; no contact email by
# default — kept generic and honest.)
_USER_AGENT = "HealthFitnessPlatform/1.0 (self-hosted; https://github.com/)"
_TIMEOUT_SECONDS = 8.0


async def get_cached_off_food(db: AsyncSession, barcode: str) -> Food | None:
    """Return the cached shared OFF Food for ``barcode``, or None if not cached."""
    stmt = select(Food).where(
        Food.off_id == barcode,
        Food.source == OFF_SOURCE,
        Food.user_id.is_(None),
    )
    return (await db.execute(stmt)).scalars().first()


async def lookup_barcode(
    db: AsyncSession,
    barcode: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Food | None:
    """Resolve a barcode to a shared OFF Food (cache-first), or None.

    None means "couldn't resolve to an honest Food" (not found, incomplete
    macros, or a network error) — the caller falls back to manual entry. On a
    cache hit no network call is made.
    """
    cached = await get_cached_off_food(db, barcode)
    if cached is not None:
        return cached

    product = await _fetch_off_product(barcode, transport=transport)
    if product is None:
        return None

    try:
        mapped = map_off_product(barcode, product)
    except OffMappingError as exc:
        log.info("OFF product %s unusable: %s", barcode, exc)
        return None

    return await _persist_off_food(db, mapped)


async def _fetch_off_product(
    barcode: str, *, transport: httpx.AsyncBaseTransport | None
) -> dict | None:
    """Fetch one OFF product payload, or None on not-found / any error.

    Returns the ``product`` dict on OFF ``status: 1``; None when the product is
    absent (``status: 0``) or the call fails (network/timeout/non-2xx/non-JSON) —
    a fail-soft path so a flaky OFF never blocks logging.
    """
    url = _OFF_URL.format(barcode=barcode)
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT_SECONDS, transport=transport
        ) as client:
            resp = await client.get(url, params={"fields": _OFF_FIELDS}, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("OFF lookup for %s failed (%s)", barcode, type(exc).__name__)
        return None

    if not isinstance(data, dict) or data.get("status") != 1:
        # status 0 = product not found (or a malformed body).
        return None
    product = data.get("product")
    return product if isinstance(product, dict) else None


async def _persist_off_food(db: AsyncSession, mapped: MappedFood) -> Food:
    """Persist a mapped OFF product as a shared Food; race-safe on the slug.

    On a concurrent first-scan that already inserted the same barcode, the unique
    index ``uq_food_global_slug`` fires; we roll back the failed insert and return
    the row the other writer committed (re-select by slug).
    """
    food = Food(
        user_id=None,
        slug=mapped.slug,
        name=mapped.name,
        brand=mapped.brand,
        serving_size=mapped.serving_size,
        serving_unit=mapped.serving_unit,
        calories=mapped.calories,
        protein_g=mapped.protein_g,
        carbs_g=mapped.carbs_g,
        fat_g=mapped.fat_g,
        source=mapped.source,
        off_id=mapped.off_id,
    )
    db.add(food)
    try:
        await db.flush()
    except IntegrityError:
        # Another request cached the same barcode first — use the winner.
        await db.rollback()
        existing = (
            await db.execute(
                select(Food).where(
                    Food.slug == off_slug(mapped.off_id), Food.user_id.is_(None)
                )
            )
        ).scalars().first()
        if existing is None:  # pragma: no cover - the conflicting row must exist
            raise
        return existing
    return food
