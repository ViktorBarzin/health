"""Connections API — per-user BYOT integrations (connections, ADR-0006).

CONTEXT.md ("Connector"): "A per-user, opt-in integration that brings an external
platform's data in." This router lets a user connect a data source with their
**own** token, pull on demand, see status, and disconnect:

* ``GET  /api/connections`` — the catalog of connectable providers, each with this
  user's connection state (connected? status? last sync?). **Never** a token.
* ``POST /api/connections`` — connect (or re-connect) a provider by pasting the
  token. The token is encrypted at rest and never returned. 503 if the server has
  no encryption key configured (fail closed — never store a token unprotected).
* ``POST /api/connections/{provider}/sync`` — pull now. Returns the resulting
  status + how many records landed; an invalid token surfaces ``status=error``
  (200, not a 500).
* ``DELETE /api/connections/{provider}`` — disconnect (delete the Connection).

Every endpoint is per-user scoped via ``get_current_user``: a user can only see,
sync, or disconnect their own Connections.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.connection import ConnectionProvider
from app.models.user import User
from app.schemas.connection import (
    ConnectionConnect,
    ConnectionRead,
    ProviderInfo,
    SyncResult,
)
from app.services.connection_query import (
    ConnectionNotFound,
    create_connection,
    disconnect_connection,
    get_connection,
    list_connections,
    sync_connection,
)
from app.services.connectors import available_providers
from app.services.crypto import CredentialCipher, EncryptionNotConfigured

router = APIRouter()


# Per-provider presentation metadata for the UI catalog. Kept here (not the DB)
# because it's static content tied to the code-level provider, like the Principle
# seed's in-code authoring. One entry per registered provider.
_PROVIDER_META: dict[ConnectionProvider, dict[str, str]] = {
    ConnectionProvider.oura: {
        "label": "Oura Ring",
        "description": (
            "Connect your Oura Ring to bring in HRV, resting heart rate and "
            "sleep — powering your daily Readiness."
        ),
        # Where the user generates a Personal Access Token (BYOT).
        "instructions_url": "https://cloud.ouraring.com/personal-access-tokens",
    },
}


def get_credential_cipher() -> CredentialCipher:
    """Dependency: the configured credential cipher, or 503 if no key is set.

    Failing closed (503) rather than storing a token unprotected is the deliberate
    behaviour when ``CONNECTION_ENCRYPTION_KEY`` is unset.
    """
    cipher = CredentialCipher.from_settings()
    if cipher is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Connections are unavailable: the server has no credential "
                "encryption key configured."
            ),
        )
    return cipher


@router.get("", response_model=list[ProviderInfo])
async def list_available_connections(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ProviderInfo]:
    """List connectable providers with the caller's own connection state."""
    own = {c.provider: c for c in await list_connections(db, user=user)}
    catalog: list[ProviderInfo] = []
    for provider in available_providers():
        meta = _PROVIDER_META.get(provider, {})
        conn = own.get(provider)
        catalog.append(
            ProviderInfo(
                provider=provider,
                label=meta.get("label", provider.value.title()),
                description=meta.get("description", ""),
                instructions_url=meta.get("instructions_url", ""),
                connected=conn is not None,
                status=conn.status if conn else None,
                last_sync_at=conn.last_sync_at if conn else None,
                last_error=conn.last_error if conn else None,
            )
        )
    return catalog


@router.post("", response_model=ConnectionRead)
async def connect_provider(
    payload: ConnectionConnect,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cipher: CredentialCipher = Depends(get_credential_cipher),
) -> ConnectionRead:
    """Connect (or re-connect) a provider by pasting the user's own token.

    The token is encrypted before storage and never returned. Re-connecting the
    same provider replaces the stored credential on the existing row.
    """
    conn = await create_connection(
        db,
        user=user,
        provider=payload.provider,
        credential=payload.token,
        cipher=cipher,
    )
    await db.commit()
    await db.refresh(conn)
    return ConnectionRead(
        provider=conn.provider,
        connected=True,
        status=conn.status,
        last_sync_at=conn.last_sync_at,
        last_error=conn.last_error,
    )


@router.post("/{provider}/sync", response_model=SyncResult)
async def sync_now(
    provider: ConnectionProvider,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    cipher: CredentialCipher = Depends(get_credential_cipher),
) -> SyncResult:
    """Pull this provider's data for the caller now.

    Returns the resulting status. A provider/auth failure is reported as
    ``status=error`` (HTTP 200) rather than a 500 — the sync never crashes.
    """
    try:
        conn = await get_connection(db, user=user, provider=provider)
    except ConnectionNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {provider.value} connection to sync.",
        )
    outcome = await sync_connection(
        db,
        connection=conn,
        cipher=cipher,
        now=datetime.now(timezone.utc),
    )
    await db.commit()
    return SyncResult(
        provider=provider,
        status=outcome.status,
        records_ingested=outcome.records_ingested,
        last_sync_at=outcome.last_sync_at,
        last_error=outcome.last_error,
    )


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_provider(
    provider: ConnectionProvider,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Disconnect (delete) the caller's Connection for ``provider``."""
    try:
        await disconnect_connection(db, user=user, provider=provider)
    except ConnectionNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No {provider.value} connection to disconnect.",
        )
    await db.commit()
