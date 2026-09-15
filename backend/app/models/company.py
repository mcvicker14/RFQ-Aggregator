import uuid

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid, pg_enum
from app.models.enums import CompanyType, OpportunityCompanyRelationship


class Company(UUIDPKMixin, TimestampMixin, Base):
    """Unifies Organizations / Companies / Teaming Partners / Competitors from the
    long-term spec — a firm's role changes per opportunity, tracked on the
    OpportunityCompany join, not by duplicating the firm's record. See
    docs/DATABASE_SCHEMA.md §Design decisions."""

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    company_type: Mapped[CompanyType] = mapped_column(pg_enum(CompanyType), default=CompanyType.OTHER)
    website: Mapped[str | None] = mapped_column(String(500), default=None)
    headquarters_city: Mapped[str | None] = mapped_column(String(120), default=None)
    headquarters_state: Mapped[str | None] = mapped_column(String(2), default=None)
    other_locations: Mapped[str | None] = mapped_column(Text, default=None)
    naics_codes: Mapped[str | None] = mapped_column(String(500), default=None)  # comma-separated
    technical_specialties: Mapped[str | None] = mapped_column(Text, default=None)

    # Socioeconomic status — directly relevant to Principal's SDVOSB teaming strategy
    is_sdvosb: Mapped[bool] = mapped_column(Boolean, default=False)
    is_vosb: Mapped[bool] = mapped_column(Boolean, default=False)
    is_hubzone: Mapped[bool] = mapped_column(Boolean, default=False)
    is_eight_a: Mapped[bool] = mapped_column(Boolean, default=False)
    is_wosb: Mapped[bool] = mapped_column(Boolean, default=False)
    is_edwosb: Mapped[bool] = mapped_column(Boolean, default=False)
    is_dbe: Mapped[bool] = mapped_column(Boolean, default=False)
    is_small_business: Mapped[bool] = mapped_column(Boolean, default=False)

    federal_experience_summary: Mapped[str | None] = mapped_column(Text, default=None)
    agencies_served: Mapped[str | None] = mapped_column(Text, default=None)
    contract_vehicles: Mapped[str | None] = mapped_column(Text, default=None)

    relationship_strength: Mapped[int | None] = mapped_column(default=None)  # 1-5, Principal's own relationship
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    is_sample_data: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class OpportunityCompany(UUIDPKMixin, TimestampMixin, Base):
    """Join: which companies are relevant to an opportunity, and how."""

    __tablename__ = "opportunity_companies"

    opportunity_id: Mapped[uuid.UUID] = fk_uuid("opportunities.id")
    company_id: Mapped[uuid.UUID] = fk_uuid("companies.id")
    # Named relationship_type, not "relationship" — that name would shadow the
    # sqlalchemy.orm.relationship import used two lines down for the `company` link.
    relationship_type: Mapped[OpportunityCompanyRelationship] = mapped_column(
        pg_enum(OpportunityCompanyRelationship), nullable=False
    )
    rationale: Mapped[str | None] = mapped_column(
        Text, default=None
    )  # why this company is listed — required for competitor entries per spec §10
    confidence: Mapped[str] = mapped_column(String(30), default="verified_fact")

    company: Mapped["Company"] = relationship()
