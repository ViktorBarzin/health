"""Pydantic schemas for the Connections endpoints (connections, ADR-0006 BYOT).

CONTEXT.md ("Connector"): a per-user, opt-in integration that brings an external
platform's data in. The wire shapes here are deliberately built so the user's
credential is **write-only**:

* :class:`ConnectionConnect` is the only place a token appears — on **input**, on
  connect. It is validated non-blank and never echoed back.
* No read schema (:class:`ProviderInfo`, :class:`ConnectionRead`,
  :class:`SyncResult`) has a token / credential field of any kind — not even a
  masked or last-4 hint. A token leak is structurally impossible from a response.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, field_validator

from app.models.connection import ConnectionProvider, ConnectionStatus


class ProviderInfo(BaseModel):
    """One connectable provider + this user's connection state (for the UI list).

    Carries presentation metadata (label, blurb, where to get the token) and the
    user's own status — never any credential.
    """

    provider: ConnectionProvider
    label: str
    description: str
    # Where the user generates their token (the "get your token" link).
    instructions_url: str
    # Whether this provider is a bring-your-own-**token** provider (the only kind
    # built now). Future OAuth providers (Whoop) would set this False and drive a
    # redirect flow instead of a paste field.
    token_based: bool = True
    # This user's connection state for the provider.
    connected: bool = False
    status: ConnectionStatus | None = None
    last_sync_at: dt.datetime | None = None
    last_error: str | None = None


class ConnectionConnect(BaseModel):
    """Connect (or re-connect) a provider by pasting the user's own token.

    The ONLY schema that carries a token, and only inbound. ``token`` is required
    and must be non-blank; it is encrypted server-side before storage and never
    returned.
    """

    provider: ConnectionProvider
    token: str = Field(min_length=1)

    @field_validator("token")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("token must not be blank")
        return v


class ConnectionRead(BaseModel):
    """A user's Connection as returned after connect — status only, no token."""

    provider: ConnectionProvider
    connected: bool = True
    status: ConnectionStatus
    last_sync_at: dt.datetime | None = None
    last_error: str | None = None


class SyncResult(BaseModel):
    """Outcome of a "sync now" — status + how much landed, never a token."""

    provider: ConnectionProvider
    status: ConnectionStatus
    records_ingested: int
    last_sync_at: dt.datetime | None = None
    last_error: str | None = None
