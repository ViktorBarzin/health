"""LLM analysis layer storage (ADR-0011, plan M5): coach's notes + Proposals.

``analysis_reports`` — one narrative per (Program, training week): the qwen
digest of that week's Adherence/outcome signals. The input digest is stored
alongside the prose so every sentence is auditable against the numbers it saw.

``proposals`` — CONTEXT.md "Proposal": a structured change the LLM suggested.
NEVER applied on its own: approval routes through the engine's validation
(clamped to Principle bounds) and lands as a receipted Program revision
(trigger=proposal). Rejections are kept — they're signal too.
"""

import datetime as dt
import enum
import uuid

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProposalStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


_STATUS_ENUM = SAEnum(
    ProposalStatus,
    name="proposal_status",
    values_callable=lambda e: [m.value for m in e],
)


class AnalysisReport(Base):
    """One coach's-notes narrative for one training week of one Program."""

    __tablename__ = "analysis_reports"
    __table_args__ = (
        # One report per (program, week) — the weekly cadence's idempotence key.
        Index("uq_analysis_report_week", "program_id", "week", unique=True),
        Index("ix_analysis_reports_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The 1-based training week the report covers (a COMPLETE week).
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    # The deterministic digest the LLM was shown — the audit trail.
    digest: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Proposal(Base):
    """One LLM-suggested Program change awaiting the user's verdict."""

    __tablename__ = "proposals"
    __table_args__ = (Index("ix_proposals_user_status", "user_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("programs.id", ondelete="CASCADE"),
        nullable=False,
    )
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("analysis_reports.id", ondelete="SET NULL"),
        nullable=True,
    )
    # {lever: "volume", muscle, to, reason} — the structured suggestion. The
    # engine re-derives "from" and clamps "to" at approval time; the stored
    # value is what the LLM asked for, the receipt records what was applied.
    change: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[ProposalStatus] = mapped_column(
        _STATUS_ENUM, nullable=False, default=ProposalStatus.pending
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
