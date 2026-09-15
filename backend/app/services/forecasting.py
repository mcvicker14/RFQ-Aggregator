"""Revenue/pipeline forecasting, spec §19. Weighted value is always computed here
(estimated_fee * win_probability), never stored as an independently-editable field,
so it can't drift from its inputs.
"""
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agency import Agency
from app.models.enums import OpportunityStatus
from app.models.forecast import RevenueForecast, RevenueTarget
from app.models.opportunity import Opportunity
from app.models.pipeline import PipelineStage
from app.schemas.forecast import ForecastSummary, ForecastSummaryBucket


def weighted_value(forecast: RevenueForecast) -> float:
    if forecast.estimated_fee is None or forecast.win_probability_pct is None:
        return 0.0
    return float(forecast.estimated_fee) * (float(forecast.win_probability_pct) / 100.0)


def _bucket(rows: list[tuple[str, RevenueForecast, bool]]) -> list[ForecastSummaryBucket]:
    agg: dict[str, dict] = defaultdict(lambda: {"total": 0.0, "weighted": 0.0, "committed": 0.0, "count": 0})
    for label, fc, is_won in rows:
        agg[label]["total"] += float(fc.total_contract_value or 0)
        agg[label]["weighted"] += weighted_value(fc)
        agg[label]["committed"] += float(fc.estimated_fee or 0) if is_won else 0.0
        agg[label]["count"] += 1
    return [
        ForecastSummaryBucket(
            label=label,
            total_pipeline=v["total"],
            weighted_pipeline=v["weighted"],
            committed_revenue=v["committed"],
            opportunity_count=v["count"],
        )
        for label, v in sorted(agg.items())
    ]


def build_forecast_summary(db: Session, target_period_label: str | None = None) -> ForecastSummary:
    rows = db.execute(
        select(RevenueForecast, Opportunity)
        .join(Opportunity, Opportunity.id == RevenueForecast.opportunity_id)
        .where(Opportunity.status == OpportunityStatus.ACTIVE)
    ).all()

    by_month, by_quarter, by_year, by_agency, by_market = [], [], [], [], []
    month_rows, quarter_rows, year_rows, agency_rows, market_rows = [], [], [], [], []

    agencies = {a.id: a for a in db.execute(select(Agency)).scalars().all()}
    stages = {s.id: s for s in db.execute(select(PipelineStage)).scalars().all()}

    total_pipeline = weighted_pipeline = committed_revenue = 0.0

    for fc, opp in rows:
        stage = stages.get(opp.pipeline_stage_id)
        is_won = bool(stage and stage.is_closed_won)
        total_pipeline += float(fc.total_contract_value or 0)
        weighted_pipeline += weighted_value(fc)
        if is_won:
            committed_revenue += float(fc.estimated_fee or 0)

        ref_date: date | None = fc.expected_award_date or (opp.proposal_due_at.date() if opp.proposal_due_at else None)
        if ref_date:
            month_rows.append((ref_date.strftime("%Y-%m"), fc, is_won))
            q = (ref_date.month - 1) // 3 + 1
            quarter_rows.append((f"{ref_date.year}-Q{q}", fc, is_won))
            year_rows.append((str(ref_date.year), fc, is_won))

        agency_label = agencies[opp.agency_id].name if opp.agency_id in agencies else "Unassigned"
        agency_rows.append((agency_label, fc, is_won))

        market_label = fc.market_sector or "Unclassified"
        market_rows.append((market_label, fc, is_won))

    target_row = None
    if target_period_label:
        target_row = db.execute(
            select(RevenueTarget).where(RevenueTarget.period_label == target_period_label)
        ).scalars().first()
    target_amount = float(target_row.target_amount) if target_row else 0.0

    return ForecastSummary(
        total_pipeline=total_pipeline,
        weighted_pipeline=weighted_pipeline,
        committed_revenue=committed_revenue,
        target_revenue=target_amount,
        revenue_gap=max(0.0, target_amount - committed_revenue),
        by_month=_bucket(month_rows),
        by_quarter=_bucket(quarter_rows),
        by_year=_bucket(year_rows),
        by_agency=_bucket(agency_rows),
        by_market_sector=_bucket(market_rows),
    )
