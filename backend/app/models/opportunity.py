import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ProvenanceMixin, TimestampMixin, UUIDPKMixin, fk_uuid, pg_enum
from app.models.enums import ContractType, MaturityStage, OpportunityStatus, SetAsideType


class Opportunity(UUIDPKMixin, TimestampMixin, ProvenanceMixin, Base):
    __tablename__ = "opportunities"

    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    agency_id: Mapped[uuid.UUID | None] = fk_uuid("agencies.id", nullable=True)
    agency_office_id: Mapped[uuid.UUID | None] = fk_uuid("agency_offices.id", nullable=True)
    solicitation_number: Mapped[str | None] = mapped_column(String(120), default=None, index=True)

    location_city: Mapped[str | None] = mapped_column(String(120), default=None)
    location_state: Mapped[str | None] = mapped_column(String(2), default=None, index=True)

    naics_code: Mapped[str | None] = mapped_column(String(10), default=None)
    psc_code: Mapped[str | None] = mapped_column(String(10), default=None)
    set_aside: Mapped[SetAsideType] = mapped_column(
        pg_enum(SetAsideType), default=SetAsideType.UNRESTRICTED, index=True
    )
    contract_type: Mapped[ContractType] = mapped_column(pg_enum(ContractType), default=ContractType.OTHER)

    estimated_value_low: Mapped[float | None] = mapped_column(Numeric(14, 2), default=None)
    estimated_value_high: Mapped[float | None] = mapped_column(Numeric(14, 2), default=None)
    estimated_fee: Mapped[float | None] = mapped_column(Numeric(14, 2), default=None)
    contract_duration_months: Mapped[int | None] = mapped_column(default=None)

    proposal_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)
    questions_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    site_visit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    industry_day_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    sources_sought_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    incumbent_company_id: Mapped[uuid.UUID | None] = fk_uuid("companies.id", nullable=True)
    incumbent_notes: Mapped[str | None] = mapped_column(Text, default=None)

    description: Mapped[str | None] = mapped_column(Text, default=None)
    scope_summary: Mapped[str | None] = mapped_column(Text, default=None)
    evaluation_factors: Mapped[str | None] = mapped_column(Text, default=None)
    past_performance_requirements: Mapped[str | None] = mapped_column(Text, default=None)
    internal_notes: Mapped[str | None] = mapped_column(Text, default=None)

    opportunity_source_label: Mapped[str] = mapped_column(
        String(120), default="Manual Entry"
    )  # "SAM.gov", "Referral", "Agency Forecast", etc. — display label, distinct from ProvenanceMixin.source

    pipeline_stage_id: Mapped[uuid.UUID | None] = fk_uuid("pipeline_stages.id", nullable=True)
    maturity_stage: Mapped[MaturityStage] = mapped_column(
        pg_enum(MaturityStage), default=MaturityStage.SOLICITATION_RELEASED
    )
    status: Mapped[OpportunityStatus] = mapped_column(pg_enum(OpportunityStatus), default=OpportunityStatus.ACTIVE)

    is_sdvosb_setaside: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_sample_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    created_by_id: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
    assigned_user_id: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)

    external_notice_id: Mapped[str | None] = mapped_column(
        String(120), default=None, index=True
    )  # e.g. SAM.gov noticeId, for dedupe on re-sync
    locked_fields: Mapped[list[str]] = mapped_column(
        JSONB, default=list
    )  # field names a human has edited; ingestion will not overwrite these — see docs/DATA_INGESTION.md

    pipeline_stage: Mapped["PipelineStage | None"] = relationship()


class OpportunitySource(UUIDPKMixin, TimestampMixin, Base):
    """Append-only log of every ingestion/discovery event that touched this
    opportunity — distinct from ProvenanceMixin on Opportunity itself, which reflects
    only the current/most authoritative source. See docs/DATABASE_SCHEMA.md §Provenance."""

    __tablename__ = "opportunity_sources"

    opportunity_id: Mapped[uuid.UUID] = fk_uuid("opportunities.id")
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000), default=None)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence: Mapped[str] = mapped_column(String(30), default="verified_fact")
    raw_snapshot: Mapped[dict | None] = mapped_column(JSONB, default=None)  # raw payload for audit/debug
    notes: Mapped[str | None] = mapped_column(Text, default=None)
