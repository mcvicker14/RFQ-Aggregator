import uuid
from datetime import date

from sqlalchemy import Date, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid


class WinLossReview(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "win_loss_reviews"

    opportunity_id: Mapped[uuid.UUID] = fk_uuid("opportunities.id", nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)  # "won" | "lost" | "no_bid"
    winner_company_id: Mapped[uuid.UUID | None] = fk_uuid("companies.id", nullable=True)
    winning_team_notes: Mapped[str | None] = mapped_column(Text, default=None)
    award_amount: Mapped[float | None] = mapped_column(Numeric(14, 2), default=None)
    decision_date: Mapped[date | None] = mapped_column(Date, default=None)

    why_won_lost: Mapped[str | None] = mapped_column(Text, default=None)
    debrief_notes: Mapped[str | None] = mapped_column(Text, default=None)
    evaluation_scores_notes: Mapped[str | None] = mapped_column(Text, default=None)
    relationship_strength_notes: Mapped[str | None] = mapped_column(Text, default=None)
    technical_weaknesses: Mapped[str | None] = mapped_column(Text, default=None)
    proposal_weaknesses: Mapped[str | None] = mapped_column(Text, default=None)
    pricing_issues: Mapped[str | None] = mapped_column(Text, default=None)
    past_performance_gaps: Mapped[str | None] = mapped_column(Text, default=None)

    recorded_by_id: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
