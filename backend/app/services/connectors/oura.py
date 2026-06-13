"""Oura connector — the BYOT reference provider (connections, ADR-0006).

The clean bring-your-own-token case (research 2026-06-13): the user generates a
**Personal Access Token** at cloud.ouraring.com — no app registration, no OAuth
flow, no infra host — and pastes it. We pull the recovery-relevant data from the
**Oura API v2** server-side (so the token never reaches the browser) and map it to
the ``health_records`` / ``category_records`` metric types Readiness (#14) reads.

Why the ``sleep`` endpoint
=========================
``GET /v2/usercollection/sleep`` returns full per-night sleep documents, each
carrying all three recovery signals in one call (verified shape, Oura API v2):

* ``average_hrv`` (ms) → ``HeartRateVariabilitySDNN`` — Readiness's HRV input.
* ``lowest_heart_rate`` (bpm) → ``RestingHeartRate`` — the lowest HR during sleep
  is the standard resting-HR proxy and matches Readiness's RHR input. (The
  ``daily_*`` summary endpoints return scores/contributors, not the raw biometric
  in our units — the sleep documents are the right source.)
* ``total_sleep_duration`` (seconds) → a ``SleepAnalysis`` **asleep interval**
  ending at ``bedtime_end`` — so the existing Readiness/dashboard sleep
  aggregation (sum ``end_time − time`` over ``%Asleep%`` intervals, bucketed by
  the night's end day) sums it into hours/night exactly like Apple Health.

Each metric sample is timestamped at the night's ``bedtime_end`` (when the
recovery state is finalised — one reading per night, the daily-mean cadence the
Readiness query expects). Mapping mirrors the Apple Health record shape so Oura
data and Apple data are interchangeable downstream:

* the persisted category ``value`` is the raw ``HKCategoryValueSleepAnalysisAsleep``
  string (what the ``%Asleep%`` filter matches), with a cleaned ``"Asleep"``
  ``value_label`` — identical to the XML importer.

Honesty rule (mirrors the OFF/Fitbod skip-don't-fabricate): a night missing a
metric (or with a non-numeric/non-positive value) contributes only the metrics it
*has* — never a zero/None sample.

The HTTP call uses an **injectable transport** (the same pattern as
:mod:`app.services.off_lookup`) so tests mock Oura and never hit the network.
"""

from __future__ import annotations

import datetime as dt
import logging

import httpx

from app.models.connection import ConnectionProvider
from app.services.connectors.base import (
    ConnectorAuthError,
    ConnectorError,
    NormalizedRecord,
    SourceConnector,
)

log = logging.getLogger(__name__)

#: The DataSource name pulled Oura records are attributed to (CONTEXT.md "Source").
OURA_SOURCE_NAME = "Oura"

# Oura API v2 sleep documents — one call gives HRV + RHR + sleep duration.
_OURA_BASE = "https://api.ouraring.com"
_SLEEP_PATH = "/v2/usercollection/sleep"
_TIMEOUT_SECONDS = 15.0

#: How far back to pull when a Connection has never synced (no ``since``). 60 days
#: is enough to seed a Readiness baseline (28-day window) without a huge backfill.
_DEFAULT_BACKFILL_DAYS = 60

# Apple-Health-compatible target types/units so Oura data reads identically to
# imported Apple data (Readiness + dashboard already key on these).
_HRV_METRIC = "HeartRateVariabilitySDNN"
_HRV_UNIT = "ms"
_RHR_METRIC = "RestingHeartRate"
_RHR_UNIT = "count/min"
_SLEEP_CATEGORY = "SleepAnalysis"
# Raw HK value (matched by the %Asleep% filter) + cleaned label, exactly as the
# XML importer persists them.
_SLEEP_VALUE_RAW = "HKCategoryValueSleepAnalysisAsleep"
_SLEEP_VALUE_LABEL = "Asleep"


def _as_float(raw: object) -> float | None:
    """Coerce a JSON number to a positive float, or None (skip — never fake a 0)."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return value if value > 0.0 else None


def _parse_ts(raw: object) -> dt.datetime | None:
    """Parse an Oura ISO-8601 timestamp to an aware UTC datetime, or None."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


class OuraConnector(SourceConnector):
    """Pulls HRV / resting HR / sleep from the Oura API v2 (BYOT via PAT)."""

    provider = ConnectionProvider.oura
    source_name = OURA_SOURCE_NAME

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # Injectable transport → tests mock Oura, no network. None ⇒ real HTTP.
        self._transport = transport

    async def pull(
        self, credential: str, since: dt.datetime | None
    ) -> list[NormalizedRecord]:
        """Fetch Oura sleep documents since ``since`` and map them to records.

        Raises :class:`ConnectorAuthError` on a 401/403 (invalid/expired PAT) and
        :class:`ConnectorError` on any other failure. Never writes to the DB.
        """
        start_date = self._start_date(since)
        documents = await self._fetch_sleep(credential, start_date)
        return self._map_documents(documents)

    # -- HTTP ---------------------------------------------------------------- #

    def _start_date(self, since: dt.datetime | None) -> dt.date:
        if since is not None:
            return since.astimezone(dt.timezone.utc).date()
        return (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=_DEFAULT_BACKFILL_DAYS)
        ).date()

    async def _fetch_sleep(self, credential: str, start_date: dt.date) -> list[dict]:
        """GET the sleep documents from ``start_date`` to today (paginated).

        Follows ``next_token`` so a long backfill returns every page. The PAT
        travels only in the Authorization header (never in a log line).
        """
        headers = {
            "Authorization": f"Bearer {credential}",
            "Accept": "application/json",
        }
        params: dict[str, str] = {"start_date": start_date.isoformat()}
        documents: list[dict] = []
        try:
            async with httpx.AsyncClient(
                base_url=_OURA_BASE,
                timeout=_TIMEOUT_SECONDS,
                transport=self._transport,
            ) as client:
                next_token: str | None = None
                # Bound the pagination loop defensively (a runaway token won't
                # spin forever); 60 days of sleep is a handful of pages.
                for _ in range(50):
                    page_params = dict(params)
                    if next_token:
                        page_params["next_token"] = next_token
                    resp = await client.get(
                        _SLEEP_PATH, params=page_params, headers=headers
                    )
                    if resp.status_code in (401, 403):
                        raise ConnectorAuthError(
                            "Oura rejected the token — it may be invalid, expired, "
                            "or missing the required scope. Generate a fresh "
                            "Personal Access Token at cloud.ouraring.com and "
                            "reconnect."
                        )
                    resp.raise_for_status()
                    body = resp.json()
                    if not isinstance(body, dict):
                        raise ConnectorError("Oura returned an unexpected response.")
                    documents.extend(
                        d for d in body.get("data", []) if isinstance(d, dict)
                    )
                    next_token = body.get("next_token")
                    if not next_token:
                        break
        except ConnectorError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            # Network/timeout/non-2xx/non-JSON — transient, distinct from auth.
            log.warning("Oura pull failed (%s)", type(exc).__name__)
            raise ConnectorError(
                "Couldn't reach Oura right now — please try again later."
            ) from exc
        return documents

    # -- Mapping ------------------------------------------------------------- #

    def _map_documents(self, documents: list[dict]) -> list[NormalizedRecord]:
        records: list[NormalizedRecord] = []
        for doc in documents:
            bedtime_end = _parse_ts(doc.get("bedtime_end"))
            if bedtime_end is None:
                # Without an instant we can't place the samples — skip the night.
                continue

            hrv = _as_float(doc.get("average_hrv"))
            if hrv is not None:
                records.append(
                    NormalizedRecord(
                        kind="metric",
                        type=_HRV_METRIC,
                        value=hrv,
                        unit=_HRV_UNIT,
                        time=bedtime_end,
                    )
                )

            rhr = _as_float(doc.get("lowest_heart_rate"))
            if rhr is not None:
                records.append(
                    NormalizedRecord(
                        kind="metric",
                        type=_RHR_METRIC,
                        value=rhr,
                        unit=_RHR_UNIT,
                        time=bedtime_end,
                    )
                )

            duration_s = _as_float(doc.get("total_sleep_duration"))
            if duration_s is not None:
                # One asleep interval ending at bedtime_end; the Readiness query
                # sums (end - time) bucketed by end day → hours/night.
                start = bedtime_end - dt.timedelta(seconds=duration_s)
                records.append(
                    NormalizedRecord(
                        kind="category",
                        type=_SLEEP_CATEGORY,
                        unit="",
                        time=start,
                        end_time=bedtime_end,
                        # value column = raw HK string (matched by %Asleep%);
                        # value_label = cleaned "Asleep" — exactly the XML path.
                        category_value=_SLEEP_VALUE_RAW,
                        value_label=_SLEEP_VALUE_LABEL,
                    )
                )
        return records
