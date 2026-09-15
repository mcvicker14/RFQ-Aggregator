import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid


class NaicsCode(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "naics_codes"

    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_core_market: Mapped[bool] = mapped_column(default=False)  # Principal's primary NAICS codes


class Discipline(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "disciplines"

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    category: Mapped[str | None] = mapped_column(String(120), default=None)


class OpportunityDiscipline(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "opportunity_disciplines"

    opportunity_id: Mapped[uuid.UUID] = fk_uuid("opportunities.id")
    discipline_id: Mapped[uuid.UUID] = fk_uuid("disciplines.id")
