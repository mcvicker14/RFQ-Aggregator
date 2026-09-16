from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import (
    ConnectorType,
    IntelligenceCategory,
    JurisdictionLevel,
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
    triggered_by: SyncTriggeredBy


class SyncAllResult(BaseModel):
    sources_attempted: int
    sources_succeeded: int
    sources_skipped: list[str]  # names of sources skipped (not enabled / no connector) or that errored, with why
