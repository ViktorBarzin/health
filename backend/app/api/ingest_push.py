"""Apple Health push-ingest API (M7, ADR-0012) — /api/ingest.

Two auth worlds in one router, deliberately:

- ``/tokens`` CRUD uses the normal forward-auth identity (Settings UI).
- ``POST /apple`` authenticates ONLY via the per-user bearer token — it is
  served on the public auth-free host (ADR-0012), where the ingress strips
  every ``X-authentik-*`` header, so the forward-auth identity can never be
  spoofed through it and this route never consults it.

The body may be the Shortcut's CSV lines (``text/plain``) or JSON; everything
lands through the same idempotent dedup + rollup recompute as every other
Import, attributed to the ``Apple Shortcut`` Source with an ImportBatch per
POST.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.ingest import parse_csv, parse_json
from app.services.ingest_query import (
    create_token,
    land_payload,
    list_tokens,
    resolve_token,
    revoke_token,
)

router = APIRouter()

#: A Shortcut push is a few hundred lines at most; anything bigger is a
#: misdirected bulk import (that's what export.zip is for).
_MAX_BODY_BYTES = 2 * 1024 * 1024


class TokenCreate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    model_config = {"extra": "forbid"}


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
async def mint_token(
    payload: TokenCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Mint an ingest token — the PLAINTEXT is returned once, here only."""
    row, plaintext = await create_token(db, user.id, label=payload.label)
    return {
        "id": str(row.id),
        "label": row.label,
        "prefix": row.prefix,
        "token": plaintext,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/tokens")
async def tokens(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """The caller's tokens — prefix + last-used only, never the secret."""
    return [
        {
            "id": str(t.id),
            "label": t.label,
            "prefix": t.prefix,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        }
        for t in await list_tokens(db, user.id)
    ]


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke(
    token_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke a token (the Shortcut using it starts getting 401s)."""
    if not await revoke_token(db, user.id, token_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.post("/apple")
async def ingest_apple(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The push receiver: bearer-token auth, CSV or JSON body, idempotent."""
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    now = datetime.now(timezone.utc)
    user_id = await resolve_token(db, token, now=now)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid ingest token",
        )

    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="payload too large — use the export.zip import for bulk history",
        )

    content_type = (request.headers.get("content-type") or "").lower()
    if "json" in content_type:
        import json

        try:
            doc = json.loads(body or b"{}")
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid JSON body",
            ) from exc
        if not isinstance(doc, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="expected a JSON object",
            )
        payload = parse_json(doc)
    else:
        payload = parse_csv(body.decode("utf-8", errors="replace"))

    return await land_payload(db, user_id, payload)
