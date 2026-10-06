from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from app.models.enums import (
    ContractType,
    MaturityStage,
    OpportunityStatus,
    SetAsideType,
    StatusBoardMatchMethod,
    StatusBoardSyncStatus,
)
from app.schemas.agency import AgencyRead
from app.schemas.common import ORMModel
from app.schemas.validators import AwareDatetime


class OpportunityBase(BaseModel):
    title: str
    agency_id: UUID | None = None
    agency_office_id: UUID | None = None
    solicitation_number: str | None = None
    location_city: str | None = None
    location_state: str | None = None
    naics_code: str | None = None
    psc_code: str | None = None
    set_aside: SetAsideType = SetAsideType.UNRESTRICTED
    contract_type: ContractType = ContractType.OTHER
    estimated_value_low: float | None = None
    estimated_value_high: float | None = None
    estimated_fee: float | None = None
    contract_duration_months: int | None = None
    proposal_due_at: AwareDatetime | None = None
    questions_due_at: AwareDatetime | None = None
    site_visit_at: AwareDatetime | None = None
    industry_day_at: AwareDatetime | None = None
    sources_sought_due_at: AwareDatetime | None = None
    incumbent_company_id: UUID | None = None
    incumbent_notes: str | None = None
    description: str | None = None
    scope_summary: str | None = None
    evaluation_factors: str | None = None
    past_performance_requirements: str | None = None
    internal_notes: str | None = None
    opportunity_source_label: str = "Manual Entry"
    pipeline_stage_id: UUID | None = None
    maturity_stage: MaturityStage = MaturityStage.SOLICITATION_RELEASED
    assigned_user_id: UUID | None = None


class OpportunityCreate(OpportunityBase):
    # Set only by Discover's "Track Opportunity" action — links the new Opportunity
    # back to the IntelligenceItem it came from (the same IntelligenceItem.opportunity_id
    # column the automatic sync-time promotion path already writes; see
    # app/services/intelligence_sync.py::promote_intelligence_item()), so Discover can
    # show "Tracked" instead of offering to create a duplicate. Never persisted on
    # Opportunity itself -- see create_opportunity()'s handling below.
    source_intelligence_item_id: UUID | None = None


class OpportunityUpdate(BaseModel):
    title: str | None = None
    agency_id: UUID | None = None
    agency_office_id: UUID | None = None
    solicitation_number: str | None = None
    location_city: str | None = None
    location_state: str | None = None
    naics_code: str | None = None
    psc_code: str | None = None
    set_aside: SetAsideType | None = None
    contract_type: ContractType | None = None
    estimated_value_low: float | None = None
    estimated_value_high: float | None = None
    estimated_fee: float | None = None
    contract_duration_months: int | None = None
    proposal_due_at: AwareDatetime | None = None
    questions_due_at: AwareDatetime | None = None
    site_visit_at: AwareDatetime | None = None
    industry_day_at: AwareDatetime | None = None
    sources_sought_due_at: AwareDatetime | None = None
    incumbent_company_id: UUID | None = None
    incumbent_notes: str | None = None
    description: str | None = None
    scope_summary: str | None = None
    evaluation_factors: str | None = None
    past_performance_requirements: str | None = None
    internal_notes: str | None = None
    pipeline_stage_id: UUID | None = None
    maturity_stage: MaturityStage | None = None
    assigned_user_id: UUID | None = None
    status: OpportunityStatus | None = None


class OpportunityListItem(ORMModel):
    id: UUID
    title: str
    solicitation_number: str | None
    location_state: str | None
    set_aside: SetAsideType
    contract_type: ContractType
    estimated_value_high: float | None
    estimated_fee: float | None
    proposal_due_at: datetime | None
    pipeline_stage_id: UUID | None
    maturity_stage: MaturityStage
    status: OpportunityStatus
    is_sdvosb_setaside: bool
    is_sample_data: bool
    agency: AgencyRead | None = None
    current_score: int | None = None
    current_score_band: str | None = None


class OpportunityRead(OpportunityBase, ORMModel):
    id: UUID
    status: OpportunityStatus
    is_sdvosb_setaside: bool
    is_sample_data: bool
    source: str
    source_url: str | None
    retrieved_at: datetime
    confidence: str
    created_at: datetime
    updated_at: datetime
    agency: AgencyRead | None = None
    current_score: int | None = None
    current_score_band: str | None = None


class StageChangeRequest(BaseModel):
    pipeline_stage_id: UUID
    note: str | None = None


class StatusBoardSyncRequest(BaseModel):
    # Free-text carried over from Discover's own rationale for this item (e.g. the
    # relevance score's "why it fits" text) — never invented if the caller has nothing
    # to say; see app/services/status_board_sync.py's Notes column mapping.
    notes: str | None = None


class StatusBoardSyncRead(ORMModel):
    id: UUID
    opportunity_id: UUID
    status: StatusBoardSyncStatus
    sheet_row_number: int | None
    attempt_count: int
    last_error: str | None
    last_attempted_at: datetime | None
    synced_at: datetime | None


class StatusBoardRowRead(ORMModel):
    source_record_id: str | None = None
    source_revision: str | None = None
    id: UUID
    sheet_row_number: int
    date_added: str | None
    due_date: str | None
    due_time: str | None
    client_project_location: str | None
    rfq_title: str
    digital_option: str | None
    standard_form: str | None
    submit_y_n: str | None
    date_submitted: str | None
    importance: str | None
    quality: str | None
    probability: str | None
    go_bys: str | None
    notes: str | None
    submitted_y_n: str | None
    link: str | None
    due_date_parsed: date | None
    is_submit_y: bool
    is_submitted_y: bool
    opportunity_id: UUID | None
    match_method: StatusBoardMatchMethod
    is_manual_entry: bool
    last_synced_at: datetime


class StatusBoardListResponse(ORMModel):
    submit_edits_enabled: bool = False
    rows: list[StatusBoardRowRead]
    last_sync_attempted_at: datetime | None
    last_sync_succeeded_at: datetime | None
    last_error: str | None
    sheet_url: str | None


class StatusBoardSubmitEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    source_record_id: UUID
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_submit: str = Field(max_length=10)
    value: Literal["Y", "N"]


class StatusBoardSubmitResult(BaseModel):
    request_id: str
    status: Literal["confirmed"]
    source_record_id: str
    value: Literal["Y", "N"]


class StatusBoardCountsRead(ORMModel):
    """Same shared status_board_filters.py predicates that back the Status Board
    page's own filtered views -- see app/services/status_board_filters.py. Every count
    here is exactly len(apply_status_board_filter(all_rows, <name>)), so a Dashboard
    number and its "click to view" destination can never drift apart."""

    on_status_board: int
    selected_to_submit: int
    due_soon: int
    submitted: int
    past_due: int
