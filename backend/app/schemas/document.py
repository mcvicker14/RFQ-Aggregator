from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import DocumentCategory
from app.schemas.common import ORMModel


class OpportunityDocumentRead(ORMModel):
    id: UUID
    opportunity_id: UUID
    category: DocumentCategory
    original_filename: str
    content_type: str | None
    size_bytes: int | None
    version: int
    uploaded_by_id: UUID | None
    notes: str | None
    created_at: datetime


class AiSolicitationAnalysisRead(ORMModel):
    id: UUID
    document_id: UUID
    opportunity_id: UUID
    model_used: str
    analyzed_at: datetime
    executive_summary: str | None
    scope: str | None
    deliverables: list | None
    required_disciplines: list | None
    relevant_naics: list | None
    contract_type: str | None
    evaluation_factors: list | None
    page_limits: str | None
    required_forms: list | None
    key_personnel_requirements: str | None
    past_performance_requirements: str | None
    submission_instructions: str | None
    deadline: str | None
    questions_deadline: str | None
    site_visit: str | None
    interview_requirements: str | None
    small_business_requirements: str | None
    subcontracting_requirements: str | None
    licensing_requirements: str | None
    geographic_restrictions: str | None
    top_10_things_to_know: list | None
    red_flags: list | None


class NotConfiguredResponse(BaseModel):
    configured: bool = False
    detail: str
    setup_instructions: str
