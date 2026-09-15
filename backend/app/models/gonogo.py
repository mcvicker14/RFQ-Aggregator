import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid, pg_enum
from app.models.enums import GoNoGoOutcome

# Default Go/No-Go criteria, spec §5. Each scored 1-5 by the user running the review.
DEFAULT_GONOGO_CRITERIA = [
    "Strategic alignment",
    "Client relationship",
    "Past performance",
    "Technical capability",
    "Key personnel",
    "Geographic advantage",
    "Teaming strength",
    "Competitive position",
    "Profitability",
    "Proposal effort",
    "Schedule",
    "Contract risk",
    "Probability of award",
    "SDVOSB advantage",
    "Incumbent strength",
]


class GoNoGoReview(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "gonogo_reviews"

    opportunity_id: Mapped[uuid.UUID] = fk_uuid("opportunities.id")
    ai_recommendation: Mapped[str | None] = mapped_column(String(30), default=None)  # suggested outcome, advisory only
    ai_recommendation_rationale: Mapped[str | None] = mapped_column(Text, default=None)

    decision: Mapped[GoNoGoOutcome | None] = mapped_column(pg_enum(GoNoGoOutcome), default=None)
    decided_by_id: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    decision_notes: Mapped[str | None] = mapped_column(Text, default=None)

    criteria_scores: Mapped[list["GoNoGoCriteriaScore"]] = relationship(
        back_populates="review", cascade="all, delete-orphan"
    )


class GoNoGoCriteriaScore(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "gonogo_criteria_scores"

    review_id: Mapped[uuid.UUID] = fk_uuid("gonogo_reviews.id")
    criterion: Mapped[str] = mapped_column(String(120), nullable=False)
    score: Mapped[int] = mapped_column(nullable=False)  # 1-5
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    review: Mapped["GoNoGoReview"] = relationship(back_populates="criteria_scores")
