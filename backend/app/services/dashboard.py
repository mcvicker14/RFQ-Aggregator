"""Executive dashboard aggregation, spec §1. Aggregates in Python over the active
opportunity set rather than SQL GROUP BY — simpler to read and entirely adequate at
this application's current data volume; if/when the pipeline grows into the
thousands, these queries are the place to push the aggregation into SQL.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.agency import Agency
from app.models.enums import IntelligenceCategory, MaturityStage, OpportunityStatus, SourceHealthStatus, TaskStatus
from app.models.gonogo import GoNoGoReview
from app.models.intelligence import IntelligenceItem, IntelligenceSource
from app.models.opportunity import Opportunity
from app.models.pipeline import PipelineStage
from app.models.scoring import OpportunityScore
from app.models.task import Task
from app.models.user import User
from app.schemas.dashboard import ChartBucket, DashboardSummary, IntelligenceKpis, KpiCards
from app.schemas.opportunity import OpportunityListItem
from app.schemas.task import TaskRead
from app.services.app_settings import hide_sample_data_by_default
from app.services.sam_relevance_scoring import RELEVANT_THRESHOLD

EARLY_STAGES = {
    MaturityStage.RUMORED_CONCEPTUAL, MaturityStage.FUNDING_IDENTIFIED, MaturityStage.PLANNING,
    MaturityStage.PROCUREMENT_FORECAST, MaturityStage.SOURCES_SOUGHT_RFI, MaturityStage.SOLICITATION_EXPECTED,
}


def _to_buckets(agg: dict[str, tuple[float, int]]) -> list[ChartBucket]:
    return [
        ChartBucket(label=label, value=value, count=count)
        for label, (value, count) in sorted(agg.items(), key=lambda kv: kv[1][0], reverse=True)
    ]


def _opportunity_to_list_item(opp: Opportunity, agency: Agency | None, score: OpportunityScore | None) -> OpportunityListItem:
    return OpportunityListItem(
        id=opp.id, title=opp.title, solicitation_number=opp.solicitation_number,
        location_state=opp.location_state, set_aside=opp.set_aside, contract_type=opp.contract_type,
        estimated_value_high=opp.estimated_value_high, estimated_fee=opp.estimated_fee,
        proposal_due_at=opp.proposal_due_at, pipeline_stage_id=opp.pipeline_stage_id,
        maturity_stage=opp.maturity_stage, status=opp.status, is_sdvosb_setaside=opp.is_sdvosb_setaside,
        is_sample_data=opp.is_sample_data, agency=agency, current_score=score.score if score else None,
        current_score_band=score.band if score else None,
    )


def _build_intelligence_kpis(
    db: Session, user: User, now: datetime, week_ago: datetime, include_samples: bool
) -> IntelligenceKpis:
    # Excludes SAM.gov items below RELEVANT_THRESHOLD by default — the same "is this
    # even worth Principal's attention" bar Discover's default view uses (see
    # app/services/sam_relevance_scoring.py). A raw fetch/error count for SAM.gov
    # itself is still fully visible on the Source Manager page; this is specifically
    # about not flooding the *intelligence* counts a user reads as "what's new to look
    # at." Never excludes any other source — those have no SAM relevance score at all.
    item_query = select(IntelligenceItem).where(
        or_(IntelligenceItem.sam_relevance_score.is_(None), IntelligenceItem.sam_relevance_score >= RELEVANT_THRESHOLD)
    )
    if not include_samples:
        item_query = item_query.where(IntelligenceItem.is_sample_data.is_(False))
    items = db.execute(item_query).scalars().all()

    counts_by_category = {c: 0 for c in IntelligenceCategory}
    new_this_week = 0
    for item in items:
        counts_by_category[item.intelligence_category] += 1
        if item.first_detected_at >= week_ago:
            new_this_week += 1

    today = now.date()
    sources = db.execute(select(IntelligenceSource)).scalars().all()
    sources_checked_today = sum(
        1 for s in sources if s.last_attempted_sync_at and s.last_attempted_sync_at.date() == today
    )
    sources_with_errors = sum(
        1 for s in sources if s.health_status in (SourceHealthStatus.FAILING, SourceHealthStatus.DEGRADED)
    )

    last_viewed_at = user.intelligence_last_viewed_at
    new_since_last_view = sum(
        1 for item in items if last_viewed_at is None or item.first_detected_at > last_viewed_at
    )
    # Advances the marker for next time — this load's own count is reported against
    # the *old* value, captured above before this line changes it. See
    # docs/PHASE2_ARCHITECTURE.md §11 and the User.intelligence_last_viewed_at comment.
    user.intelligence_last_viewed_at = now
    db.commit()

    return IntelligenceKpis(
        live_opportunity_count=counts_by_category[IntelligenceCategory.LIVE_OPPORTUNITY],
        pre_solicitation_count=counts_by_category[IntelligenceCategory.PRE_SOLICITATION],
        early_signal_count=counts_by_category[IntelligenceCategory.EARLY_SIGNAL],
        award_intelligence_count=counts_by_category[IntelligenceCategory.AWARD_INTELLIGENCE],
        new_this_week=new_this_week,
        sources_checked_today=sources_checked_today,
        sources_with_errors=sources_with_errors,
        new_intelligence_since_last_view=new_since_last_view,
        last_viewed_at=last_viewed_at,
    )


def _high_priority_signals(db: Session, include_samples: bool, limit: int = 10) -> list[IntelligenceItem]:
    query = select(IntelligenceItem).where(
        IntelligenceItem.intelligence_category == IntelligenceCategory.EARLY_SIGNAL,
        IntelligenceItem.opportunity_id.is_(None),
        IntelligenceItem.early_signal_score.isnot(None),
    )
    if not include_samples:
        query = query.where(IntelligenceItem.is_sample_data.is_(False))
    query = query.order_by(IntelligenceItem.early_signal_score.desc()).limit(limit)
    return db.execute(query).scalars().all()


def build_dashboard_summary(db: Session, user: User) -> DashboardSummary:
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    thirty_days = now + timedelta(days=30)

    # Sample data is included by default (unchanged behavior) unless an administrator
    # has explicitly turned this on — see docs/PHASE2_ARCHITECTURE.md §9. This is a
    # deliberate opt-in, not a silent change to numbers a user may already be checking.
    # Shared by the opportunity, intelligence-item, and high-priority-signal queries
    # below, so sample visibility stays consistent across every part of this summary.
    include_samples = not hide_sample_data_by_default(db)
    opp_query = select(Opportunity).where(Opportunity.status == OpportunityStatus.ACTIVE)
    if not include_samples:
        opp_query = opp_query.where(Opportunity.is_sample_data.is_(False))
    opportunities = db.execute(opp_query).scalars().all()
    stages = {s.id: s for s in db.execute(select(PipelineStage)).scalars().all()}
    agencies = {a.id: a for a in db.execute(select(Agency)).scalars().all()}

    scores_by_opp: dict = {}
    for score in db.execute(select(OpportunityScore)).scalars().all():
        existing = scores_by_opp.get(score.opportunity_id)
        if existing is None or score.computed_at > existing.computed_at:
            scores_by_opp[score.opportunity_id] = score

    reviews_by_opp = {r.opportunity_id: r for r in db.execute(select(GoNoGoReview)).scalars().all()}

    total_value = total_fee = 0.0
    discovered_this_week = due_30 = awaiting_gonogo = 0
    active_proposals = interviews_pending = awards_pending = wins = losses = 0
    sdvosb_count = limited_competition_count = recompete_count = early_stage_count = 0

    by_stage: dict[str, list] = defaultdict(lambda: [0.0, 0])
    by_agency: dict[str, list] = defaultdict(lambda: [0.0, 0])
    by_state: dict[str, list] = defaultdict(lambda: [0.0, 0])
    by_source: dict[str, list] = defaultdict(lambda: [0.0, 0])
    by_contract_type: dict[str, list] = defaultdict(lambda: [0.0, 0])
    by_naics: dict[str, list] = defaultdict(lambda: [0.0, 0])
    by_score_band: dict[str, list] = defaultdict(lambda: [0.0, 0])
    by_month: dict[str, list] = defaultdict(lambda: [0.0, 0])

    upcoming_deadlines: list[Opportunity] = []

    for opp in opportunities:
        fee = float(opp.estimated_fee or 0)
        value = float(opp.estimated_value_high or opp.estimated_value_low or 0)
        total_value += value
        total_fee += fee

        if opp.created_at >= week_ago:
            discovered_this_week += 1
        if opp.proposal_due_at and now <= opp.proposal_due_at <= thirty_days:
            due_30 += 1
            upcoming_deadlines.append(opp)
        if opp.is_sdvosb_setaside:
            sdvosb_count += 1
        if opp.set_aside.value != "unrestricted":
            limited_competition_count += 1
        if opp.incumbent_company_id is not None:
            recompete_count += 1
        if opp.maturity_stage in EARLY_STAGES:
            early_stage_count += 1

        stage = stages.get(opp.pipeline_stage_id)
        stage_name = stage.name if stage else "Unassigned"
        review = reviews_by_opp.get(opp.id)
        if stage_name == "Go/No-Go" or (review and review.decision is None):
            awaiting_gonogo += 1
        if stage_name in ("Proposal Development", "Submitted"):
            active_proposals += 1
        if stage_name == "Interview":
            interviews_pending += 1
        if stage_name == "Award Pending":
            awards_pending += 1
        if stage and stage.is_closed_won:
            wins += 1
        if stage_name == "Lost":
            losses += 1

        by_stage[stage_name][0] += fee
        by_stage[stage_name][1] += 1

        agency = agencies.get(opp.agency_id)
        # short_name (e.g. "USACE") keeps chart Y-axis labels from wrapping/colliding —
        # full name is still shown elsewhere (agency profile, opportunity detail).
        agency_label = (agency.short_name or agency.name) if agency else "Unassigned"
        by_agency[agency_label][0] += fee
        by_agency[agency_label][1] += 1

        state_label = opp.location_state or "Unknown"
        by_state[state_label][0] += fee
        by_state[state_label][1] += 1

        by_source[opp.opportunity_source_label][0] += fee
        by_source[opp.opportunity_source_label][1] += 1

        by_contract_type[opp.contract_type.value][0] += fee
        by_contract_type[opp.contract_type.value][1] += 1

        naics_label = opp.naics_code or "Unclassified"
        by_naics[naics_label][0] += fee
        by_naics[naics_label][1] += 1

        score = scores_by_opp.get(opp.id)
        band_label = score.band if score else "unscored"
        by_score_band[band_label][0] += fee
        by_score_band[band_label][1] += 1

        month_label = opp.created_at.strftime("%Y-%m")
        by_month[month_label][0] += fee
        by_month[month_label][1] += 1

    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else None

    kpis = KpiCards(
        total_active_opportunities=len(opportunities),
        total_estimated_contract_value=total_value,
        total_estimated_fee=total_fee,
        discovered_this_week=discovered_this_week,
        due_within_30_days=due_30,
        awaiting_go_no_go=awaiting_gonogo,
        active_proposals=active_proposals,
        interviews_pending=interviews_pending,
        awards_pending=awards_pending,
        wins=wins,
        losses=losses,
        win_rate_pct=win_rate,
        sdvosb_setaside_count=sdvosb_count,
        sole_source_or_limited_competition_count=limited_competition_count,
        recompete_count=recompete_count,
        early_stage_count=early_stage_count,
    )

    ranked = sorted(
        opportunities,
        key=lambda o: (
            -(scores_by_opp[o.id].score if o.id in scores_by_opp else 0),
            o.proposal_due_at or datetime.max.replace(tzinfo=timezone.utc),
        ),
    )
    highest_priority = ranked[:10]

    upcoming_deadlines.sort(key=lambda o: o.proposal_due_at)

    tasks = db.execute(
        select(Task).where(Task.status.in_([TaskStatus.OPEN, TaskStatus.IN_PROGRESS]))
    ).scalars().all()
    today = date.today()
    attention_tasks = [t for t in tasks if t.due_date and t.due_date <= today]
    attention_tasks.sort(key=lambda t: t.due_date)

    opp_titles = {o.id: o.title for o in opportunities}

    intelligence_kpis = _build_intelligence_kpis(db, user, now, week_ago, include_samples)
    high_priority_signals = _high_priority_signals(db, include_samples)

    return DashboardSummary(
        kpis=kpis,
        intelligence=intelligence_kpis,
        pipeline_by_stage=_to_buckets(by_stage),
        pipeline_by_agency=_to_buckets(by_agency),
        pipeline_by_state=_to_buckets(by_state),
        pipeline_by_source=_to_buckets(by_source),
        pipeline_by_contract_type=_to_buckets(by_contract_type),
        pipeline_by_naics=_to_buckets(by_naics),
        pipeline_by_score_band=_to_buckets(by_score_band),
        pipeline_value_over_time=[
            ChartBucket(label=label, value=v, count=c) for label, (v, c) in sorted(by_month.items())
        ],
        upcoming_deadlines=[
            _opportunity_to_list_item(o, agencies.get(o.agency_id), scores_by_opp.get(o.id))
            for o in upcoming_deadlines[:10]
        ],
        highest_priority_opportunities=[
            _opportunity_to_list_item(o, agencies.get(o.agency_id), scores_by_opp.get(o.id))
            for o in highest_priority
        ],
        high_priority_signals=list(high_priority_signals),
        attention_today_tasks=[
            TaskRead(
                id=t.id, opportunity_id=t.opportunity_id, opportunity_title=opp_titles.get(t.opportunity_id),
                title=t.title, notes=t.notes, owner_id=t.owner_id, due_date=t.due_date,
                priority=t.priority, status=t.status, created_by_id=t.created_by_id,
            )
            for t in attention_tasks[:20]
        ],
    )
