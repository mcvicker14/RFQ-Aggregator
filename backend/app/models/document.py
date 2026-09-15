import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid, pg_enum, utcnow
from app.models.enums import DocumentCategory


class OpportunityDocument(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "opportunity_documents"

    opportunity_id: Mapped[uuid.UUID] = fk_uuid("opportunities.id")
    category: Mapped[DocumentCategory] = mapped_column(pg_enum(DocumentCategory), default=DocumentCategory.OTHER)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False)  # opaque path, not user-controlled
    content_type: Mapped[str | None] = mapped_column(String(120), default=None)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    version: Mapped[int] = mapped_column(default=1)
    replaces_document_id: Mapped[uuid.UUID | None] = fk_uuid("opportunity_documents.id", nullable=True)
    uploaded_by_id: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)


class AiSolicitationAnalysis(UUIDPKMixin, TimestampMixin, Base):
    """Structured extraction result from the AI Solicitation Reader, spec §7.
    Always linked to the source document; every field traceable back to it — see
    docs/ARCHITECTURE.md §AI solicitation reader."""

    __tablename__ = "ai_solicitation_analyses"

    document_id: Mapped[uuid.UUID] = fk_uuid("opportunity_documents.id")
    opportunity_id: Mapped[uuid.UUID] = fk_uuid("opportunities.id")

    model_used: Mapped[str] = mapped_column(String(120), nullable=False)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    executive_summary: Mapped[str | None] = mapped_column(Text, default=None)
    scope: Mapped[str | None] = mapped_column(Text, default=None)
    deliverables: Mapped[list | None] = mapped_column(JSONB, default=None)
    required_disciplines: Mapped[list | None] = mapped_column(JSONB, default=None)
    relevant_naics: Mapped[list | None] = mapped_column(JSONB, default=None)
    contract_type: Mapped[str | None] = mapped_column(String(120), default=None)
    evaluation_factors: Mapped[list | None] = mapped_column(JSONB, default=None)
    page_limits: Mapped[str | None] = mapped_column(String(255), default=None)
    required_forms: Mapped[list | None] = mapped_column(JSONB, default=None)
    key_personnel_requirements: Mapped[str | None] = mapped_column(Text, default=None)
    past_performance_requirements: Mapped[str | None] = mapped_column(Text, default=None)
    submission_instructions: Mapped[str | None] = mapped_column(Text, default=None)
    deadline: Mapped[str | None] = mapped_column(String(120), default=None)
    questions_deadline: Mapped[str | None] = mapped_column(String(120), default=None)
    site_visit: Mapped[str | None] = mapped_column(String(255), default=None)
    interview_requirements: Mapped[str | None] = mapped_column(Text, default=None)
    small_business_requirements: Mapped[str | None] = mapped_column(Text, default=None)
    subcontracting_requirements: Mapped[str | None] = mapped_column(Text, default=None)
    licensing_requirements: Mapped[str | None] = mapped_column(Text, default=None)
    geographic_restrictions: Mapped[str | None] = mapped_column(Text, default=None)
    top_10_things_to_know: Mapped[list | None] = mapped_column(JSONB, default=None)
    red_flags: Mapped[list | None] = mapped_column(JSONB, default=None)

    raw_model_response: Mapped[dict | None] = mapped_column(JSONB, default=None)  # full response, for audit
