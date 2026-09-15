from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import GoNoGoOutcome
from app.schemas.common import ORMModel


class GoNoGoCriteriaScoreUpsert(BaseModel):
    criterion: str
    score: int  # 1-5
    notes: str | None = None


class GoNoGoCriteriaScoreRead(ORMModel):
    id: UUID
    criterion: str
    score: int
    notes: str | None = None


class GoNoGoReviewRead(ORMModel):
    id: UUID
    opportunity_id: UUID
    ai_recommendation: str | None
    ai_recommendation_rationale: str | None
    decision: GoNoGoOutcome | None
    decided_by_id: UUID | None
    decided_at: datetime | None
    decision_notes: str | None
    criteria_scores: list[GoNoGoCriteriaScoreRead] = []


class GoNoGoDecisionRequest(BaseModel):
    decision: GoNoGoOutcome
    decision_notes: str | None = None
