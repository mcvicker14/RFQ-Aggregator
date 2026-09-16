from datetime import datetime

from pydantic import BaseModel

from app.schemas.intelligence import IntelligenceItemRead
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


class IntelligenceKpis(BaseModel):
    live_opportunity_count: int
    pre_solicitation_count: int
    early_signal_count: int
    award_intelligence_count: int
    new_this_week: int
    sources_checked_today: int
    sources_with_errors: int
    new_intelligence_since_last_view: int
    last_viewed_at: datetime | None  # the value *before* this load advanced it — see build_dashboard_summary


class DashboardSummary(BaseModel):
    kpis: KpiCards
    intelligence: IntelligenceKpis
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
    high_priority_signals: list[IntelligenceItemRead]
    attention_today_tasks: list[TaskRead]
