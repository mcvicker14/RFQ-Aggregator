from uuid import UUID

from pydantic import BaseModel

from app.models.enums import CompanyType, OpportunityCompanyRelationship
from app.schemas.common import ORMModel


class CompanyBase(BaseModel):
    name: str
    company_type: CompanyType = CompanyType.OTHER
    website: str | None = None
    headquarters_city: str | None = None
    headquarters_state: str | None = None
    other_locations: str | None = None
    naics_codes: str | None = None
    technical_specialties: str | None = None
    is_sdvosb: bool = False
    is_vosb: bool = False
    is_hubzone: bool = False
    is_eight_a: bool = False
    is_wosb: bool = False
    is_edwosb: bool = False
    is_dbe: bool = False
    is_small_business: bool = False
    federal_experience_summary: str | None = None
    agencies_served: str | None = None
    contract_vehicles: str | None = None
    relationship_strength: int | None = None
    notes: str | None = None


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: str | None = None
    company_type: CompanyType | None = None
    website: str | None = None
    headquarters_city: str | None = None
    headquarters_state: str | None = None
    other_locations: str | None = None
    naics_codes: str | None = None
    technical_specialties: str | None = None
    is_sdvosb: bool | None = None
    is_vosb: bool | None = None
    is_hubzone: bool | None = None
    is_eight_a: bool | None = None
    is_wosb: bool | None = None
    is_edwosb: bool | None = None
    is_dbe: bool | None = None
    is_small_business: bool | None = None
    federal_experience_summary: str | None = None
    agencies_served: str | None = None
    contract_vehicles: str | None = None
    relationship_strength: int | None = None
    notes: str | None = None


class CompanyRead(CompanyBase, ORMModel):
    id: UUID
    is_sample_data: bool


class OpportunityCompanyCreate(BaseModel):
    company_id: UUID
    relationship_type: OpportunityCompanyRelationship
    rationale: str | None = None
    confidence: str = "verified_fact"


class OpportunityCompanyRead(ORMModel):
    id: UUID
    company: CompanyRead
    relationship_type: OpportunityCompanyRelationship
    rationale: str | None = None
    confidence: str
