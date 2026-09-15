from datetime import date
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class RevenueForecastBase(BaseModel):
    total_contract_value: float | None = None
    principal_share_pct: float | None = None
    estimated_fee: float | None = None
    win_probability_pct: float | None = None
    expected_award_date: date | None = None
    expected_revenue_start: date | None = None
    expected_revenue_end: date | None = None
    market_sector: str | None = None


class RevenueForecastUpsert(RevenueForecastBase):
    pass


class RevenueForecastRead(RevenueForecastBase, ORMModel):
    id: UUID
    opportunity_id: UUID
    weighted_value: float | None = None


class ForecastSummaryBucket(BaseModel):
    label: str
    total_pipeline: float
    weighted_pipeline: float
    committed_revenue: float
    opportunity_count: int


class ForecastSummary(BaseModel):
    total_pipeline: float
    weighted_pipeline: float
    committed_revenue: float
    target_revenue: float
    revenue_gap: float
    by_month: list[ForecastSummaryBucket]
    by_quarter: list[ForecastSummaryBucket]
    by_year: list[ForecastSummaryBucket]
    by_agency: list[ForecastSummaryBucket]
    by_market_sector: list[ForecastSummaryBucket]
