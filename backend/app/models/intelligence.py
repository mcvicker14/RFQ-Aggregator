"""Phase 2: multi-source intelligence platform. See docs/PHASE2_ARCHITECTURE.md for
the full design. `IntelligenceSource` is the "Source Registry" (one row per external
source, whether or not it has a working connector yet); `IntelligenceItem` is the
universal landing zone every connector writes to, tagged with an `intelligence_category`
that decides whether it's eligible for auto-promotion into the existing `Opportunity`
model (§2/§5) — this keeps Opportunity, OpportunitySource, and every existing
route/service untouched. `ProjectCluster` backs the deduplication engine (§6);
`IntelligenceSyncRun` is sync logging (§7); `AppSetting` is a minimal key-value store
for the sample/live data toggle (§9) and any future app-wide switch.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid, pg_enum, utcnow
from app.models.enums import (
    ConnectorType,
    DedupStatus,
    EstimatedTimeToProcurement,
    IntelligenceCategory,
    JurisdictionLevel,
    MaturityStage,
    SetAsideType,
    SourceHealthStatus,
    SyncRunStatus,
    SyncTriggeredBy,
)


class IntelligenceSource(UUIDPKMixin, TimestampMixin, Base):
    """The Source Registry. A row exists here for every source named in Phase 2's
    Wave 1 list, whether or not `connector_key` is populated yet — an unimplemented
    source is simply one with connector_key=NULL and health_status=NEEDS_CONFIGURATION
    or MANUAL_ONLY, documented via `notes` rather than faked. See §1/§8."""

    __tablename__ = "intelligence_sources"

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    organization: Mapped[str | None] = mapped_column(String(300), default=None)
    jurisdiction_level: Mapped[JurisdictionLevel] = mapped_column(pg_enum(JurisdictionLevel), nullable=False)
    geographic_coverage: Mapped[str | None] = mapped_column(String(300), default=None)

    source_url: Mapped[str | None] = mapped_column(String(1000), default=None)
    api_url: Mapped[str | None] = mapped_column(String(1000), default=None)
    connector_type: Mapped[ConnectorType] = mapped_column(pg_enum(ConnectorType), nullable=False)
    connector_key: Mapped[str | None] = mapped_column(String(60), default=None, unique=True)

    requires_auth: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    auth_notes: Mapped[str | None] = mapped_column(Text, default=None)

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    polling_frequency_hours: Mapped[int | None] = mapped_column(Integer, default=None)

    last_attempted_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_successful_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_result_count: Mapped[int | None] = mapped_column(Integer, default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    health_status: Mapped[SourceHealthStatus] = mapped_column(
        pg_enum(SourceHealthStatus), default=SourceHealthStatus.NEVER_RUN, nullable=False
    )

    terms_notes: Mapped[str | None] = mapped_column(Text, default=None)  # robots.txt / ToS / rate-limit / licensing
    parser_version: Mapped[str | None] = mapped_column(String(20), default=None)
    default_intelligence_category: Mapped[IntelligenceCategory | None] = mapped_column(
        pg_enum(IntelligenceCategory), default=None
    )
    naics_filter: Mapped[list[str] | None] = mapped_column(JSONB, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)  # research notes for not-yet-built sources


class IntelligenceItem(UUIDPKMixin, TimestampMixin, Base):
    """The universal landing row for every source. `intelligence_category` decides
    promotion eligibility (§5); `opportunity_id` is set once promoted but the row
    itself is never deleted, so the source history survives even after promotion.
    Reuses ProvenanceMixin's (source, source_url, retrieved_at, confidence) shape —
    added by hand below rather than via the mixin, so `source_url` can sit next to
    `intelligence_source_id` in the column list; behavior is identical."""

    __tablename__ = "intelligence_items"
    __table_args__ = (
        # The within-source dedup case — cross-source dedup is what ProjectCluster/
        # dedup_status is for (§6). Prevents the same sync run (or a re-run) from
        # ever double-inserting the same source item.
        UniqueConstraint("intelligence_source_id", "external_id", name="uq_intelligence_items_source_external_id"),
        {"comment": "See docs/PHASE2_ARCHITECTURE.md §3"},
    )

    intelligence_source_id: Mapped[uuid.UUID] = fk_uuid("intelligence_sources.id")
    external_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)

    agency_name: Mapped[str | None] = mapped_column(String(300), default=None)
    agency_id: Mapped[uuid.UUID | None] = fk_uuid("agencies.id", nullable=True)
    jurisdiction_level: Mapped[JurisdictionLevel | None] = mapped_column(pg_enum(JurisdictionLevel), default=None)

    location_city: Mapped[str | None] = mapped_column(String(120), default=None)
    location_state: Mapped[str | None] = mapped_column(String(2), default=None, index=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), default=None)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), default=None)

    naics_code: Mapped[str | None] = mapped_column(String(10), default=None)
    psc_code: Mapped[str | None] = mapped_column(String(10), default=None)
    set_aside: Mapped[SetAsideType | None] = mapped_column(pg_enum(SetAsideType), default=None)

    estimated_value_low: Mapped[float | None] = mapped_column(Numeric(14, 2), default=None)
    estimated_value_high: Mapped[float | None] = mapped_column(Numeric(14, 2), default=None)
    funding_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), default=None)

    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    proposal_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)
    estimated_solicitation_date: Mapped[date | None] = mapped_column(Date, default=None)
    estimated_award_date: Mapped[date | None] = mapped_column(Date, default=None)
    estimated_time_to_procurement: Mapped[EstimatedTimeToProcurement | None] = mapped_column(
        pg_enum(EstimatedTimeToProcurement), default=None
    )  # always shown in the UI labeled as an estimate — never certainty

    maturity_stage: Mapped[MaturityStage | None] = mapped_column(pg_enum(MaturityStage), default=None)
    intelligence_category: Mapped[IntelligenceCategory] = mapped_column(
        pg_enum(IntelligenceCategory), nullable=False, index=True
    )

    solicitation_number: Mapped[str | None] = mapped_column(String(120), default=None, index=True)
    contract_number: Mapped[str | None] = mapped_column(String(120), default=None)
    funding_award_number: Mapped[str | None] = mapped_column(String(120), default=None)
    project_number: Mapped[str | None] = mapped_column(String(120), default=None)

    incumbent_company_id: Mapped[uuid.UUID | None] = fk_uuid("companies.id", nullable=True)
    incumbent_name: Mapped[str | None] = mapped_column(String(300), default=None)
    awardee_company_id: Mapped[uuid.UUID | None] = fk_uuid("companies.id", nullable=True)
    awardee_name: Mapped[str | None] = mapped_column(String(300), default=None)
    is_prime_award: Mapped[bool | None] = mapped_column(Boolean, default=None)

    relevant_disciplines: Mapped[list[str] | None] = mapped_column(JSONB, default=None)

    early_signal_score: Mapped[int | None] = mapped_column(Integer, default=None)
    early_signal_score_rationale: Mapped[dict | None] = mapped_column(JSONB, default=None)

    raw_metadata: Mapped[dict | None] = mapped_column(JSONB, default=None)

    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    opportunity_id: Mapped[uuid.UUID | None] = fk_uuid("opportunities.id", nullable=True)

    dedup_status: Mapped[DedupStatus] = mapped_column(pg_enum(DedupStatus), default=DedupStatus.UNCLUSTERED, nullable=False)
    # SET NULL, not the fk_uuid default of CASCADE: deleting a cluster (just a grouping
    # anchor) must never delete the intelligence_items in it — that would violate the
    # "preserve every underlying source even when merged" requirement (§6).
    project_cluster_id: Mapped[uuid.UUID | None] = fk_uuid("project_clusters.id", nullable=True, ondelete="SET NULL")
    dedup_match_reason: Mapped[str | None] = mapped_column(Text, default=None)

    is_sample_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # ProvenanceMixin's shape, added by hand (see class docstring)
    source: Mapped[str] = mapped_column(String(120), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000), default=None)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    confidence: Mapped[str] = mapped_column(String(30), default="verified_fact", nullable=False)


class ProjectCluster(UUIDPKMixin, TimestampMixin, Base):
    """Deliberately thin — the real dedup state lives on each IntelligenceItem row
    (dedup_status, dedup_match_reason). This table is only the grouping anchor, so
    merging never deletes or combines rows. See §6."""

    __tablename__ = "project_clusters"

    representative_title: Mapped[str | None] = mapped_column(String(500), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    confirmed_by_user_id: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class IntelligenceSyncRun(UUIDPKMixin, TimestampMixin, Base):
    """One row per sync attempt, per source. See §7 — a source's own failure here
    never raises past run_sync(), so 'sync all enabled sources' always continues."""

    __tablename__ = "intelligence_sync_runs"

    intelligence_source_id: Mapped[uuid.UUID] = fk_uuid("intelligence_sources.id")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)  # NULL = still running
    status: Mapped[SyncRunStatus] = mapped_column(pg_enum(SyncRunStatus), default=SyncRunStatus.RUNNING, nullable=False)

    items_fetched: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_unchanged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_errored: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_detail: Mapped[str | None] = mapped_column(Text, default=None)

    triggered_by: Mapped[SyncTriggeredBy] = mapped_column(pg_enum(SyncTriggeredBy), nullable=False)
    triggered_by_user_id: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)


class AppSetting(Base):
    """Minimal key-value store — currently just hide_sample_data_by_default (§9).
    Doesn't use UUIDPKMixin/TimestampMixin: the natural primary key is the setting's
    own name, and there's no meaningful created_at for a row that's upserted in place."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    updated_by_user_id: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
