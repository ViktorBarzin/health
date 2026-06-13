"""Connection model — a per-user, opt-in bring-your-own-token integration.

CONTEXT.md ("Connector"): "A per-user, opt-in integration that brings an external
platform's data in." A **Connection** is one user's enabled instance of a provider
(ADR-0006, BYOT variant): the user pastes their **own** API credential (e.g. an
Oura Personal Access Token) and we pull recovery data from that provider on demand
and on a schedule, normalising it into the same idempotent ingest path as every
other Source.

Security-critical invariants (the whole point of this model)
============================================================
* The user's credential is stored **encrypted at rest** in ``encrypted_credential``
  (Fernet ciphertext, a ``bytea``) — NEVER plaintext. It is written via
  :class:`app.services.crypto.CredentialCipher` before insert and only ever
  decrypted in-memory at pull time.
* The credential is **never returned in any API response** and **never logged**.
  There is deliberately no plaintext column, no "masked" column, not even a
  last-4 hint — the model carries only the ciphertext and operational metadata
  (``status`` / ``last_sync_at`` / ``last_error``), so a leak is structurally
  impossible from a row read.

One Connection per (user, provider) — re-connecting a provider replaces the
credential on the existing row (see :mod:`app.services.connection_query`). The
``provider`` and ``status`` enums are native Postgres enums (the same typed-
dimension idiom as ``meal`` / ``set_type``), extensible by adding a label.
"""

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ConnectionProvider(str, enum.Enum):
    """An external platform a Connection can bring data in from (ADR-0006).

    Extensible — a new provider is one new label here plus one
    :class:`~app.services.connectors.base.SourceConnector` subclass registered in
    the provider registry. Starts with Oura (the clean BYOT/PAT case); Whoop
    (OAuth) and Garmin (unofficial login) are documented future labels, not built.
    """

    oura = "oura"


class ConnectionStatus(str, enum.Enum):
    """Operational state of a Connection.

    * ``active`` — connected and pulling normally.
    * ``error`` — the last pull failed (e.g. an invalid/expired token); the
      reason is in ``last_error``. The Connection is kept (not deleted) so the
      user can re-paste a token without re-adding it.
    * ``disabled`` — the user turned it off but kept the row (reserved; the
      current UI disconnects by deleting, but the state exists for a soft toggle).
    """

    active = "active"
    error = "error"
    disabled = "disabled"


# Native Postgres enums, storing the enum *values* as labels (consistent with the
# muscle / set_type / meal enums). ``create_type`` defaults to True so the test
# suite's metadata ``create_all`` provisions the types; the Alembic migration
# creates them explicitly with ``create_type=False``.
_PROVIDER_ENUM = SAEnum(
    ConnectionProvider,
    name="connection_provider",
    values_callable=lambda e: [m.value for m in e],
)
_STATUS_ENUM = SAEnum(
    ConnectionStatus,
    name="connection_status",
    values_callable=lambda e: [m.value for m in e],
)


class Connection(Base):
    """One user's opt-in connection to an external data provider (BYOT)."""

    __tablename__ = "connections"
    __table_args__ = (
        # One Connection per provider per user — re-connecting updates this row.
        UniqueConstraint("user_id", "provider", name="uq_connection_user_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[ConnectionProvider] = mapped_column(_PROVIDER_ENUM, nullable=False)

    # The user's API credential, Fernet-encrypted (see module docstring + crypto).
    # NEVER plaintext, NEVER logged, NEVER returned to the client.
    encrypted_credential: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    status: Mapped[ConnectionStatus] = mapped_column(
        _STATUS_ENUM, nullable=False, default=ConnectionStatus.active
    )
    # When the last successful pull completed (None until the first sync).
    last_sync_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Human-readable reason the last pull failed (when status == error). Never
    # contains the credential.
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
