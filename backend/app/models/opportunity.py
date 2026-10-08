import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, ProvenanceMixin, TimestampMixin, UUIDPKMixin, fk_uuid, pg_enum
from app.models.enums import (
    ContractType,
    MaturityStage,
    OpportunityStatus,
    SetAsideType,
    StatusBoardMatchMethod,
    StatusBoardSyncStatus,
)


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


class StatusBoardSync(UUIDPKMixin, TimestampMixin, Base):
    """Tracks one Opportunity's sync state against the New RFQs section of the SOQ
    Status Board Google Sheet — see app/services/status_board_sync.py for the actual
    write mechanism. The unique constraint on opportunity_id is the app-side half of
    duplicate protection: at most one sync record can ever exist per Opportunity, so a
    repeated "Track + Add to Status Board" click (or a retry) always finds this row
    first and never attempts a second independent write for the same Opportunity.
    """

    __tablename__ = "status_board_syncs"
    __table_args__ = (UniqueConstraint("opportunity_id"),)

    opportunity_id: Mapped[uuid.UUID] = fk_uuid("opportunities.id", ondelete="CASCADE")
    status: Mapped[StatusBoardSyncStatus] = mapped_column(
        pg_enum(StatusBoardSyncStatus), default=StatusBoardSyncStatus.PENDING, nullable=False, index=True
    )
    sheet_row_number: Mapped[int | None] = mapped_column(default=None)  # 1-indexed row in the Active tab, once known
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    last_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    opportunity: Mapped["Opportunity"] = relationship()


class StatusBoardRow(UUIDPKMixin, TimestampMixin, Base):
    """One row of the New RFQs section as last read back from the SOQ Status Board
    Google Sheet — see app/services/status_board_read_sync.py. The Sheet, not this
    table, is authoritative; this is a read-through cache the app never writes back
    to the sheet from. Every successful refresh deletes and fully replaces every row
    here (see that module's docstring for why) — a row's presence or absence always
    reflects the sheet's own state as of last_synced_at, never a partial merge.

    Columns are deliberately raw display strings (exactly as the sheet shows them,
    e.g. due_date "10/8/2026", submit_y_n "Y" or ""), matching FIELD_KEYS in
    app/services/status_board_sync.py / COLUMN_ORDER in
    google-apps-script/status_board_sync.gs — this app is read-only for these manual
    fields in this first version and must never reinterpret or reformat what a human
    typed into the sheet. date_added_parsed/due_date_parsed/is_submit_y/is_submitted_y
    are normalized companions used only for filtering/sorting, derived at read time,
    never displayed in place of the raw value.
    """

    __tablename__ = "status_board_rows"

    source_record_id: Mapped[str | None] = mapped_column(String(36), default=None)
    source_revision: Mapped[str | None] = mapped_column(String(64), default=None)

    sheet_row_number: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    date_added: Mapped[str | None] = mapped_column(String(50), default=None)
    due_date: Mapped[str | None] = mapped_column(String(50), default=None)
    due_time: Mapped[str | None] = mapped_column(String(50), default=None)
    client_project_location: Mapped[str | None] = mapped_column(String(500), default=None)
    rfq_title: Mapped[str] = mapped_column(String(1000), nullable=False)
    digital_option: Mapped[str | None] = mapped_column(String(200), default=None)
    standard_form: Mapped[str | None] = mapped_column(String(200), default=None)
    submit_y_n: Mapped[str | None] = mapped_column(String(10), default=None)
    date_submitted: Mapped[str | None] = mapped_column(String(50), default=None)
    importance: Mapped[str | None] = mapped_column(String(200), default=None)
    quality: Mapped[str | None] = mapped_column(String(200), default=None)
    probability: Mapped[str | None] = mapped_column(String(200), default=None)
    go_bys: Mapped[str | None] = mapped_column(String(500), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    submitted_y_n: Mapped[str | None] = mapped_column(String(10), default=None)
    link: Mapped[str | None] = mapped_column(String(1000), default=None)

    date_added_parsed: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    due_date_parsed: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    is_submit_y: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    is_submitted_y: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    opportunity_id: Mapped[uuid.UUID | None] = fk_uuid("opportunities.id", nullable=True, ondelete="SET NULL")
    match_method: Mapped[StatusBoardMatchMethod] = mapped_column(
        pg_enum(StatusBoardMatchMethod), default=StatusBoardMatchMethod.UNMATCHED, nullable=False, index=True
    )

    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    opportunity: Mapped["Opportunity | None"] = relationship()

    @property
    def is_manual_entry(self) -> bool:
        """"Not app-originated" per the product spec -- true for every row except an
        exact StatusBoardSync relationship hit, including the other 3 match tiers:
        those link display/drill-down to a real Opportunity, but the ROW ITSELF
        wasn't necessarily placed on the sheet by this app's own sync."""
        return self.match_method != StatusBoardMatchMethod.SYNC_RELATIONSHIP


class StatusBoardCacheState(UUIDPKMixin, TimestampMixin, Base):
    """Singleton row tracking the Status Board read-sync's own health, independent of
    StatusBoardRow's row count (which can legitimately be zero right after the sheet's
    New RFQs section is cleared for a new year) -- see
    app/services/status_board_read_sync.py. At most one row ever exists; callers
    always fetch-or-create it, never key off its id."""

    __tablename__ = "status_board_cache_state"

    last_sync_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_sync_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_reconciliation_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_reconciliation_slot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_reconciliation_error: Mapped[str | None] = mapped_column(Text, default=None)
