"""Connector registry — the one place a provider is registered (connections).

ADR-0006: "adding Garmin/Fitbit/Oura/Withings later is one module each, not a
rework." This registry makes that literal: a provider is a
:class:`~app.services.connectors.base.SourceConnector` subclass added to
:data:`_REGISTRY`. The sync layer and the API resolve a connector by its
:class:`~app.models.connection.ConnectionProvider` enum, so nothing else needs to
know which providers exist.

Adding a provider (e.g. Whoop, Garmin — DO NOT build now)
========================================================
1. add a label to :class:`ConnectionProvider` (+ the migration enum);
2. implement a ``SourceConnector`` subclass that maps the provider's API to
   :class:`NormalizedRecord`\\s (the credential shape is the provider's business:
   Oura = a PAT string; **Whoop** = an OAuth access token the provider refreshes;
   **Garmin** = the unofficial username/password the connector logs in with);
3. register it here.

The ingest path, encrypted-credential storage, Source/ImportBatch bookkeeping,
sync-now endpoint, scheduler, and UI are all provider-agnostic and need no change.
"""

from __future__ import annotations

from app.models.connection import ConnectionProvider
from app.services.connectors.base import SourceConnector
from app.services.connectors.oura import OuraConnector

# The single source of "which providers exist". One entry per provider.
_REGISTRY: dict[ConnectionProvider, SourceConnector] = {
    ConnectionProvider.oura: OuraConnector(),
}


def get_connector(provider: ConnectionProvider) -> SourceConnector:
    """Return the connector for ``provider``.

    Raises ``KeyError`` if the provider has no registered connector (a
    programming error — every enum label should have one).
    """
    return _REGISTRY[provider]


def available_providers() -> list[ConnectionProvider]:
    """The providers a user can connect, in a stable order."""
    return list(_REGISTRY.keys())


__all__ = ["get_connector", "available_providers"]
