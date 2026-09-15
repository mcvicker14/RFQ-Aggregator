from datetime import date
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class WinLossReviewCreate(BaseModel):
    outcome: str  # "won" | "lost" | "no_bid"
    winner_company_id: UUID | None = None
    winning_team_notes: str | None = None
    award_amount: float | None = None
    decision_date: date | None = None
    why_won_lost: str | None = None
    debrief_notes: str | None = None
    evaluation_scores_notes: str | None = None
    relationship_strength_notes: str | None = None
    technical_weaknesses: str | None = None
    proposal_weaknesses: str | None = None
    pricing_issues: str | None = None
    past_performance_gaps: str | None = None


class WinLossReviewRead(WinLossReviewCreate, ORMModel):
    id: UUID
    opportunity_id: UUID
    recorded_by_id: UUID | None
