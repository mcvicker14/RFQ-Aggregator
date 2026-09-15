import uuid
from datetime import date

from sqlalchemy import Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid, pg_enum
from app.models.enums import ContactRole


class Contact(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "contacts"

    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    organization: Mapped[str | None] = mapped_column(String(255), default=None)
    title: Mapped[str | None] = mapped_column(String(255), default=None)
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    agency_id: Mapped[uuid.UUID | None] = fk_uuid("agencies.id", nullable=True)
    agency_office_id: Mapped[uuid.UUID | None] = fk_uuid("agency_offices.id", nullable=True)
    company_id: Mapped[uuid.UUID | None] = fk_uuid("companies.id", nullable=True)
    role: Mapped[ContactRole] = mapped_column(pg_enum(ContactRole), default=ContactRole.OTHER)
    relationship_strength: Mapped[int | None] = mapped_column(default=None)  # 1-5
    last_contact_date: Mapped[date | None] = mapped_column(Date, default=None)
    next_follow_up_date: Mapped[date | None] = mapped_column(Date, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)


class OpportunityContact(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "opportunity_contacts"

    opportunity_id: Mapped[uuid.UUID] = fk_uuid("opportunities.id")
    contact_id: Mapped[uuid.UUID] = fk_uuid("contacts.id")
    role_on_opportunity: Mapped[ContactRole] = mapped_column(pg_enum(ContactRole), default=ContactRole.OTHER)

    contact: Mapped["Contact"] = relationship()
