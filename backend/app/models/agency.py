import uuid

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid


class Agency(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "agencies"

    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    short_name: Mapped[str | None] = mapped_column(String(50), default=None)  # e.g. "USACE"
    agency_type: Mapped[str | None] = mapped_column(
        String(50), default=None
    )  # federal / state / municipal / parish-county / authority
    parent_agency_id: Mapped[uuid.UUID | None] = fk_uuid("agencies.id", nullable=True)
    priority_tier: Mapped[int] = mapped_column(default=3)  # 1 = highest priority customer (USACE/VA/FEMA/NRCS/AF/DoD)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    is_sample_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    offices: Mapped[list["AgencyOffice"]] = relationship(back_populates="agency", cascade="all, delete-orphan")


class AgencyOffice(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "agency_offices"

    agency_id: Mapped[uuid.UUID] = fk_uuid("agencies.id")
    name: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g. "New Orleans District"
    city: Mapped[str | None] = mapped_column(String(120), default=None)
    state: Mapped[str | None] = mapped_column(String(2), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    agency: Mapped["Agency"] = relationship(back_populates="offices")
