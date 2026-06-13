"""The SourceConnector contract — one ABC every BYOT provider implements.

CONTEXT.md ("Connector") + ADR-0006: "First-party Connectors are in-repo Python
modules behind a ``SourceConnector`` ABC … each per-user opt-in with credentials
stored per user. … All [kinds] normalize into the same idempotent ingest
pipeline." This module defines that ABC and the **normalized record** every
provider emits, so the ingest path is provider-agnostic and adding a provider is
one class.

The contract
============
A provider implements :meth:`SourceConnector.pull` — given the user's decrypted
``credential`` and an optional ``since`` instant, fetch the recovery-relevant data
from the remote API and return a list of :class:`NormalizedRecord`. The connector
does **not** touch the database: it only maps the provider's shape to our normal
form. The :mod:`app.services.connection_query` sync layer then lands those records
in ``health_records`` / ``category_records`` through the existing idempotent dedup
helpers, so a re-pull never duplicates.

Why a normalized record (not "land it yourself")
================================================
Keeping the connector pure-mapping (HTTP in, normalized records out) means:

* providers are trivially unit-testable with a mocked HTTP client (no DB);
* the idempotent ingest + Source/ImportBatch bookkeeping lives in **one** place
  (the sync layer), shared by every provider — exactly the dedup reuse ADR-0006
  asks for;
* a record can target either ``health_records`` (a :class:`Metric` sample — HRV,
  resting HR) or ``category_records`` (a typed interval — sleep), which is what
  Readiness (#14) reads, via the single ``kind`` discriminator.

Errors
======
A provider raises :class:`ConnectorAuthError` when the credential is
invalid/expired (the sync layer maps this to ``status=error`` with a clear
message and never crashes), and :class:`ConnectorError` for a transient/remote
failure (the sync layer keeps the prior status and surfaces a generic message).
"""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from app.models.connection import ConnectionProvider


class ConnectorError(RuntimeError):
    """A pull failed for a transient/remote reason (network, 5xx, bad shape).

    Distinct from :class:`ConnectorAuthError`: the credential may still be valid,
    so the sync layer keeps the Connection's prior status and surfaces a generic
    "couldn't reach <provider>" message.
    """


class ConnectorAuthError(ConnectorError):
    """The credential was rejected (invalid/expired/insufficient scope).

    The sync layer sets ``status=error`` with a clear, credential-free message so
    the user knows to re-paste a token. Never carries the token itself.
    """


#: Which table a normalized record lands in. ``metric`` → ``health_records`` (a
#: :class:`Metric` sample); ``category`` → ``category_records`` (a typed interval
#: such as sleep). One discriminator keeps the ingest path uniform.
RecordKind = Literal["metric", "category"]


@dataclass(frozen=True)
class NormalizedRecord:
    """One sample a connector emits, in our provider-agnostic normal form.

    * ``kind`` — target table (``metric`` → ``health_records``, ``category`` →
      ``category_records``).
    * ``type`` — the metric/category type string (e.g. ``HeartRateVariabilitySDNN``,
      ``RestingHeartRate``, ``SleepAnalysis``) — chosen to match the values the
      rest of the app (Readiness #14, dashboard) already reads.
    * ``value`` — the numeric value for a **metric** sample (``health_records.value``).
      Ignored for a category record (use ``category_value`` / ``value_label`` there).
    * ``unit`` — the metric's unit (``ms``, ``count/min``, …); empty for a category.
    * ``time`` / ``end_time`` — the sample instant, and the interval end for a
      category record (sleep). Both timezone-aware UTC.
    * ``category_value`` — the string persisted to ``category_records.value`` (the
      column the ``%Asleep%`` sleep filter matches), e.g.
      ``"HKCategoryValueSleepAnalysisAsleep"`` — mirroring the Apple Health importer.
    * ``value_label`` — the cleaned human label persisted to
      ``category_records.value_label`` (e.g. ``"Asleep"``).
    """

    kind: RecordKind
    type: str
    unit: str
    time: dt.datetime
    value: float = 0.0
    end_time: dt.datetime | None = None
    category_value: str | None = None
    value_label: str | None = None


class SourceConnector(ABC):
    """Pulls a user's data from one external provider into normalized records.

    The swappable boundary (ADR-0006): each provider — Oura now, Whoop/Garmin
    later — implements :meth:`pull`. A connector is stateless and DB-free; the
    sync layer injects the decrypted credential and lands the result.
    """

    #: The provider this connector serves (used by the registry).
    provider: ConnectionProvider
    #: The :class:`~app.models.data_source.DataSource` name to attribute pulled
    #: records to (CONTEXT.md "Source").
    source_name: str

    @abstractmethod
    async def pull(
        self, credential: str, since: dt.datetime | None
    ) -> list[NormalizedRecord]:
        """Fetch + map the provider's recovery data to normalized records.

        ``credential`` is the user's decrypted API token; ``since`` bounds the
        pull (None ⇒ a sensible backfill window). Raises
        :class:`ConnectorAuthError` if the credential is rejected, or
        :class:`ConnectorError` on a transient/remote failure. Never writes to the
        database.
        """
        raise NotImplementedError
