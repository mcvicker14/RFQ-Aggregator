from datetime import date
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import ContactRole
from app.schemas.common import ORMModel


class ContactBase(BaseModel):
    full_name: str
    organization: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    agency_id: UUID | None = None
    agency_office_id: UUID | None = None
    company_id: UUID | None = None
    role: ContactRole = ContactRole.OTHER
    relationship_strength: int | None = None
    last_contact_date: date | None = None
    next_follow_up_date: date | None = None
    notes: str | None = None


class ContactCreate(ContactBase):
    pass


class ContactUpdate(BaseModel):
    full_name: str | None = None
    organization: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    agency_id: UUID | None = None
    agency_office_id: UUID | None = None
    company_id: UUID | None = None
    role: ContactRole | None = None
    relationship_strength: int | None = None
    last_contact_date: date | None = None
    next_follow_up_date: date | None = None
    notes: str | None = None


class ContactRead(ContactBase, ORMModel):
    id: UUID


class OpportunityContactCreate(BaseModel):
    contact_id: UUID
    role_on_opportunity: ContactRole = ContactRole.OTHER


class OpportunityContactRead(ORMModel):
    id: UUID
    contact: ContactRead
    role_on_opportunity: ContactRole
