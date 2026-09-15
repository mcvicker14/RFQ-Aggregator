from pydantic import BaseModel

from app.schemas.opportunity import OpportunityListItem
from app.schemas.task import TaskRead


class KpiCards(BaseModel):
    total_active_opportunities: int
    total_estimated_contract_value: float
    total_estimated_fee: float
    discovered_this_week: int
    due_within_30_days: int
    awaiting_go_no_go: int
    active_proposals: int
    interviews_pending: int
    awards_pending: int
    wins: int
    losses: int
    win_rate_pct: float | None
    sdvosb_setaside_count: int
    sole_source_or_limited_competition_count: int
    recompete_count: int
    early_stage_count: int


class ChartBucket(BaseModel):
    label: str
    value: float
    count: int | None = None


class DashboardSummary(BaseModel):
    kpis: KpiCards
    pipeline_by_stage: list[ChartBucket]
    pipeline_by_agency: list[ChartBucket]
    pipeline_by_state: list[ChartBucket]
    pipeline_by_source: list[ChartBucket]
    pipeline_by_contract_type: list[ChartBucket]
    pipeline_by_naics: list[ChartBucket]
    pipeline_by_score_band: list[ChartBucket]
    pipeline_value_over_time: list[ChartBucket]
    upcoming_deadlines: list[OpportunityListItem]
    highest_priority_opportunities: list[OpportunityListItem]
    attention_today_tasks: list[TaskRead]
