import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid, utcnow

# Default category weights, spec §4. Sum to 100. Editable via ScoringWeightProfile.
DEFAULT_WEIGHTS = {
    "strategic_fit": 20,
    "customer_fit": 15,
    "contract_fit": 15,
    "geographic_fit": 10,
    "competitive_advantage": 15,
    "financial_attractiveness": 10,
    "competition": 10,
    "timing": 5,
}


class ScoringWeightProfile(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "scoring_weight_profiles"

    name: Mapped[str] = mapped_column(String(120), default="Default")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    weights: Mapped[dict] = mapped_column(JSONB, default=lambda: dict(DEFAULT_WEIGHTS))
    # Geographic multipliers, spec §4 "configurable scoring" for LA/Gulf Coast/etc.
    geographic_priorities: Mapped[dict] = mapped_column(
        JSONB,
        default=lambda: {
            "LA": 100,
            "MS": 85,
            "AL": 85,
            "TX": 80,
            "FL": 75,
            "_gulf_coast_default": 70,
            "_southeast_default": 55,
            "_national_default": 35,
        },
    )
    # Agency priority multipliers, spec §4 "Customer Fit"
    agency_priority_tiers: Mapped[dict] = mapped_column(
        JSONB,
        default=lambda: {"1": 100, "2": 70, "3": 45},
    )


class OpportunityScore(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "opportunity_scores"

    opportunity_id: Mapped[uuid.UUID] = fk_uuid("opportunities.id")
    weight_profile_id: Mapped[uuid.UUID | None] = fk_uuid("scoring_weight_profiles.id", nullable=True)

    score: Mapped[int] = mapped_column(Integer, nullable=False)
    band: Mapped[str] = mapped_column(String(20), nullable=False)  # high / medium / low
    category_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {category: 0-100}
    category_rationale: Mapped[dict] = mapped_column(JSONB, nullable=False)  # {category: [bullet, ...]}
    why_it_scores_highly: Mapped[str] = mapped_column(Text, nullable=False)
    primary_concern: Mapped[str] = mapped_column(Text, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
