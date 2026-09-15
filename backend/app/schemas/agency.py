from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class AgencyOfficeBase(BaseModel):
    name: str
    city: str | None = None
    state: str | None = None
    notes: str | None = None


class AgencyOfficeCreate(AgencyOfficeBase):
    pass


class AgencyOfficeRead(AgencyOfficeBase, ORMModel):
    id: UUID
    agency_id: UUID


class AgencyBase(BaseModel):
    name: str
    short_name: str | None = None
    agency_type: str | None = None
    priority_tier: int = 3
    notes: str | None = None


class AgencyCreate(AgencyBase):
    pass


class AgencyUpdate(BaseModel):
    name: str | None = None
    short_name: str | None = None
    agency_type: str | None = None
    priority_tier: int | None = None
    notes: str | None = None


class AgencyRead(AgencyBase, ORMModel):
    id: UUID
    is_sample_data: bool
    offices: list[AgencyOfficeRead] = []
