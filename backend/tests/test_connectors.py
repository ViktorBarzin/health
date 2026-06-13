"""SourceConnector framework + the Oura reference provider (connections, ADR-0006).

These pin the connector contract:

* the **registry/ABC** — every provider is reachable by its
  :class:`ConnectionProvider` enum, implements the :class:`SourceConnector`
  contract, and adding one is just registering a class;
* the **Oura pull mapping** — a mocked Oura API v2 ``sleep`` payload maps to the
  right normalized records: HRV → ``HeartRateVariabilitySDNN`` (ms), resting HR →
  ``RestingHeartRate`` (bpm), sleep → a ``SleepAnalysis`` asleep interval (so the
  existing Readiness sleep aggregation sums it). The Oura HTTP call is **mocked**
  (``httpx.MockTransport``) — no network in tests, the same pattern as the OFF
  tests;
* **invalid/expired token → a clear auth error** (``ConnectorAuthError``), never a
  crash — the sync layer turns this into ``status=error``;
* a transient/HTTP failure raises ``ConnectorError`` (distinct from auth) so the
  sync layer can keep the old status / surface a generic message.
"""

import datetime as dt

import httpx
import pytest

from app.models.connection import ConnectionProvider
from app.services.connectors import available_providers, get_connector
from app.services.connectors.base import (
    ConnectorAuthError,
    ConnectorError,
    NormalizedRecord,
    SourceConnector,
)
from app.services.connectors.oura import (
    OURA_SOURCE_NAME,
    OuraConnector,
)

# --------------------------------------------------------------------------- #
# A representative Oura API v2 `sleep` payload (trimmed to the fields we map).
# Two nights so we can assert both map and ordering. Values chosen distinct so a
# mis-mapping is obvious.
# --------------------------------------------------------------------------- #
_OURA_SLEEP = {
    "data": [
        {
            "id": "night-1",
            "day": "2026-06-10",
            "bedtime_start": "2026-06-09T23:30:00+00:00",
            "bedtime_end": "2026-06-10T07:30:00+00:00",
            "average_hrv": 65,
            "average_heart_rate": 58.0,
            "lowest_heart_rate": 48,
            "total_sleep_duration": 27000,  # 7.5 h in seconds
            "type": "long_sleep",
        },
        {
            "id": "night-2",
            "day": "2026-06-11",
            "bedtime_start": "2026-06-10T23:00:00+00:00",
            "bedtime_end": "2026-06-11T06:30:00+00:00",
            "average_hrv": 70,
            "average_heart_rate": 56.0,
            "lowest_heart_rate": 46,
            "total_sleep_duration": 23400,  # 6.5 h
            "type": "long_sleep",
        },
    ],
    "next_token": None,
}


def _transport(payload, *, status=200, counter=None, capture=None):
    """A MockTransport returning ``payload``; optionally records calls/requests."""

    def handler(request: httpx.Request) -> httpx.Response:
        if counter is not None:
            counter.append(request.url)
        if capture is not None:
            capture.append(request)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


# --------------------------------------------------------------------------- #
# Registry / ABC
# --------------------------------------------------------------------------- #


def test_oura_is_registered_and_resolvable() -> None:
    connector = get_connector(ConnectionProvider.oura)
    assert isinstance(connector, SourceConnector)
    assert isinstance(connector, OuraConnector)
    assert connector.provider is ConnectionProvider.oura
    assert connector.source_name == OURA_SOURCE_NAME


def test_available_providers_lists_oura() -> None:
    providers = available_providers()
    assert ConnectionProvider.oura in providers
    # Every registered provider exposes a connector implementing the ABC.
    for p in providers:
        assert isinstance(get_connector(p), SourceConnector)


def test_unregistered_provider_raises() -> None:
    with pytest.raises(KeyError):
        get_connector("not-a-provider")  # type: ignore[arg-type]


def test_abc_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        SourceConnector()  # type: ignore[abstract]


# --------------------------------------------------------------------------- #
# Oura pull mapping
# --------------------------------------------------------------------------- #


async def test_pull_maps_hrv_rhr_sleep_to_normalized_records() -> None:
    connector = OuraConnector(transport=_transport(_OURA_SLEEP))
    records = await connector.pull("a-valid-pat", since=None)

    # Group by (kind, type) for assertions.
    by_type: dict[str, list[NormalizedRecord]] = {}
    for r in records:
        by_type.setdefault(r.type, []).append(r)

    # HRV → HeartRateVariabilitySDNN (ms), one per night.
    hrv = by_type["HeartRateVariabilitySDNN"]
    assert {r.value for r in hrv} == {65.0, 70.0}
    assert all(r.kind == "metric" and r.unit == "ms" for r in hrv)

    # Resting HR → RestingHeartRate (bpm) from lowest_heart_rate.
    rhr = by_type["RestingHeartRate"]
    assert {r.value for r in rhr} == {48.0, 46.0}
    assert all(r.kind == "metric" and r.unit == "count/min" for r in rhr)

    # Sleep → a SleepAnalysis asleep interval (category), hours = duration/3600.
    sleep = by_type["SleepAnalysis"]
    assert all(r.kind == "category" for r in sleep)
    # The interval duration (end - time) must equal total_sleep_duration.
    durations = {
        round((r.end_time - r.time).total_seconds()) for r in sleep
    }
    assert durations == {27000, 23400}
    # The persisted category value carries "Asleep" so the Readiness %Asleep%
    # filter matches; the cleaned label mirrors the Apple Health importer.
    assert all("Asleep" in r.category_value for r in sleep)
    assert all(r.value_label == "Asleep" for r in sleep)


async def test_pull_passes_bearer_token_and_date_range() -> None:
    captured: list[httpx.Request] = []
    connector = OuraConnector(transport=_transport(_OURA_SLEEP, capture=captured))
    since = dt.datetime(2026, 6, 1, tzinfo=dt.timezone.utc)

    await connector.pull("secret-pat", since=since)

    assert captured, "expected an Oura request"
    req = captured[0]
    # Bearer auth header carries the user's PAT.
    assert req.headers["Authorization"] == "Bearer secret-pat"
    # The sleep endpoint, with a start_date derived from `since`.
    assert "/v2/usercollection/sleep" in str(req.url)
    assert "start_date=2026-06-01" in str(req.url)


async def test_pull_with_no_since_still_queries_a_window() -> None:
    captured: list[httpx.Request] = []
    connector = OuraConnector(transport=_transport(_OURA_SLEEP, capture=captured))
    await connector.pull("pat", since=None)
    # A default backfill window is applied (a start_date is always sent).
    assert "start_date=" in str(captured[0].url)


async def test_invalid_token_raises_auth_error() -> None:
    """Oura 401 → ConnectorAuthError with a clear message (never a crash)."""
    connector = OuraConnector(
        transport=_transport({"detail": "Unauthorized"}, status=401)
    )
    with pytest.raises(ConnectorAuthError):
        await connector.pull("expired-pat", since=None)


async def test_forbidden_token_raises_auth_error() -> None:
    connector = OuraConnector(
        transport=_transport({"detail": "Forbidden"}, status=403)
    )
    with pytest.raises(ConnectorAuthError):
        await connector.pull("scopeless-pat", since=None)


async def test_server_error_raises_connector_error_not_auth() -> None:
    """A 5xx is transient — a ConnectorError, distinct from an auth failure."""
    connector = OuraConnector(
        transport=_transport({"detail": "boom"}, status=503)
    )
    with pytest.raises(ConnectorError) as exc:
        await connector.pull("pat", since=None)
    assert not isinstance(exc.value, ConnectorAuthError)


async def test_empty_data_yields_no_records() -> None:
    connector = OuraConnector(transport=_transport({"data": [], "next_token": None}))
    records = await connector.pull("pat", since=None)
    assert records == []


async def test_missing_metrics_in_a_night_are_skipped_not_faked() -> None:
    """A night missing a metric contributes only the metrics it has (no zeros)."""
    payload = {
        "data": [
            {
                "id": "n",
                "day": "2026-06-10",
                "bedtime_start": "2026-06-09T23:30:00+00:00",
                "bedtime_end": "2026-06-10T07:30:00+00:00",
                # average_hrv missing, lowest_heart_rate present, no sleep duration
                "lowest_heart_rate": 50,
                "type": "long_sleep",
            }
        ],
        "next_token": None,
    }
    connector = OuraConnector(transport=_transport(payload))
    records = await connector.pull("pat", since=None)
    types = {r.type for r in records}
    assert types == {"RestingHeartRate"}  # only the present metric
