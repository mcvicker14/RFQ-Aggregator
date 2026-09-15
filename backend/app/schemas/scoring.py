from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class OpportunityScoreRead(ORMModel):
    id: UUID
    opportunity_id: UUID
    score: int
    band: str
    category_scores: dict
    category_rationale: dict
    why_it_scores_highly: str
    primary_concern: str
    computed_at: datetime


class ScoringWeightProfileRead(ORMModel):
    id: UUID
    name: str
    is_active: bool
    weights: dict
    geographic_priorities: dict
    agency_priority_tiers: dict


class ScoringWeightProfileUpdate(BaseModel):
    weights: dict | None = None
    geographic_priorities: dict | None = None
    agency_priority_tiers: dict | None = None
