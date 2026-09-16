from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

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
from app.schemas.common import ORMModel


class IntelligenceSourceRead(ORMModel):
    id: UUID
    name: str
    organization: str | None
    jurisdiction_level: JurisdictionLevel
    geographic_coverage: str | None
    source_url: str | None
    api_url: str | None
    connector_type: ConnectorType
    connector_key: str | None
    requires_auth: bool
    auth_notes: str | None
    is_enabled: bool
    polling_frequency_hours: int | None
    last_attempted_sync_at: datetime | None
    last_successful_sync_at: datetime | None
    last_result_count: int | None
    last_error: str | None
    health_status: SourceHealthStatus
    terms_notes: str | None
    default_intelligence_category: IntelligenceCategory | None
    notes: str | None


class IntelligenceSourceUpdate(BaseModel):
    is_enabled: bool | None = None
    polling_frequency_hours: int | None = None
    notes: str | None = None


class IntelligenceSyncRunRead(ORMModel):
    id: UUID
    intelligence_source_id: UUID
    started_at: datetime
    finished_at: datetime | None
    status: SyncRunStatus
    items_fetched: int
    items_created: int
    items_updated: int
    items_unchanged: int
    items_errored: int
    error_detail: str | None
    diagnostics: dict | None
    triggered_by: SyncTriggeredBy


class SyncAllResult(BaseModel):
    sources_attempted: int
    sources_succeeded: int
    sources_skipped: list[str]  # names of sources skipped (not enabled / no connector) or that errored, with why


class IntelligenceItemRead(ORMModel):
    id: UUID
    intelligence_source_id: UUID
    external_id: str
    title: str
    description: str | None
    agency_name: str | None
    agency_id: UUID | None
    jurisdiction_level: JurisdictionLevel | None
    location_city: str | None
    location_state: str | None
    naics_code: str | None
    psc_code: str | None
    set_aside: SetAsideType | None
    estimated_value_low: float | None
    estimated_value_high: float | None
    funding_amount: float | None
    posted_at: datetime | None
    proposal_due_at: datetime | None
    estimated_solicitation_date: date | None
    estimated_award_date: date | None
    estimated_time_to_procurement: EstimatedTimeToProcurement | None
    maturity_stage: MaturityStage | None
    intelligence_category: IntelligenceCategory
    solicitation_number: str | None
    contract_number: str | None
    funding_award_number: str | None
    project_number: str | None
    incumbent_name: str | None
    awardee_name: str | None
    is_prime_award: bool | None
    relevant_disciplines: list[str] | None
    early_signal_score: int | None
    early_signal_score_rationale: dict | None
    first_detected_at: datetime
    last_seen_at: datetime
    opportunity_id: UUID | None
    dedup_status: DedupStatus
    project_cluster_id: UUID | None
    dedup_match_reason: str | None
    is_sample_data: bool
    source: str
    source_url: str | None
    retrieved_at: datetime
    confidence: str
