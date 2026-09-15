from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import ContractType, MaturityStage, OpportunityStatus, SetAsideType
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
    pass


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
