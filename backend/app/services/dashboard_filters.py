"""Named predicates shared between the dashboard's KPI aggregation
(app/services/dashboard.py) and the Opportunities list route's drill-down filter
(app/api/routes/opportunities.py, the `kpi` query param) -- the single source of
truth for "which records does this Dashboard number actually represent," so a KPI
count and the record set behind its "click to view" link can never drift apart.

Every named stage/threshold below is consumed by both sides rather than redefined
in each place: dashboard.py imports these same constants for its Python-side
aggregation loop, and apply_kpi_filter() below builds the equivalent SQL WHERE
clause for the Opportunities route. Same constants + same base scope
(Opportunity.status == ACTIVE, the same sample-data visibility) applied to the same
table guarantees the same result set, whether evaluated in Python or in SQL.
"""
from datetime import datetime, timedelta

from sqlalchemy import Select, or_, select

from app.models.enums import MaturityStage, SetAsideType
from app.models.gonogo import GoNoGoReview
from app.models.opportunity import Opportunity
from app.models.pipeline import PipelineStage

STAGE_GO_NO_GO = "Go/No-Go"
STAGE_PROPOSAL_DEVELOPMENT = "Proposal Development"
STAGE_SUBMITTED = "Submitted"
STAGE_INTERVIEW = "Interview"
STAGE_AWARD_PENDING = "Award Pending"
STAGE_LOST = "Lost"

ACTIVE_PROPOSAL_STAGE_NAMES = {STAGE_PROPOSAL_DEVELOPMENT, STAGE_SUBMITTED}

EARLY_STAGES = {
    MaturityStage.RUMORED_CONCEPTUAL, MaturityStage.FUNDING_IDENTIFIED, MaturityStage.PLANNING,
    MaturityStage.PROCUREMENT_FORECAST, MaturityStage.SOURCES_SOUGHT_RFI, MaturityStage.SOLICITATION_EXPECTED,
}

DUE_SOON_DEFAULT_DAYS = 30
DISCOVERED_RECENTLY_DAYS = 7

# Every value the Opportunities route's `kpi` query param accepts, and the Dashboard
# KPI each one corresponds to -- kept as one literal set so the route's Query(...,
# pattern=...) and the frontend's link-building can both stay in sync with this file.
KPI_FILTER_NAMES = {
    "due_soon",
    "awaiting_go_no_go",
    "active_proposals",
    "interviews_pending",
    "awards_pending",
    "sdvosb",
    "limited_competition",
    "recompete",
    "early_stage",
    "discovered_this_week",
}


def _stage_id_subquery(names: set[str] | str) -> Select:
    if isinstance(names, str):
        names = {names}
    return select(PipelineStage.id).where(PipelineStage.name.in_(names))


def awaiting_go_no_go_clause():
    """Mirrors the exact compound condition dashboard.py counts as "awaiting a Go/No-Go
    decision": the opportunity is sitting in the Go/No-Go pipeline stage, OR it has a
    GoNoGoReview whose decision is still unset (not yet decided even if the opportunity
    has since moved to a different stage)."""
    return or_(
        Opportunity.pipeline_stage_id.in_(_stage_id_subquery(STAGE_GO_NO_GO)),
        Opportunity.id.in_(select(GoNoGoReview.opportunity_id).where(GoNoGoReview.decision.is_(None))),
    )


def apply_kpi_filter(stmt: Select, kpi: str, now: datetime) -> Select:
    """Applies one named Dashboard-KPI predicate on top of an existing Opportunity
    SELECT (which the caller has already scoped to status == ACTIVE and the desired
    sample-data visibility, exactly as build_dashboard_summary() does). `now` must be
    the same instant the caller used for any other time-relative Dashboard numbers in
    the same request, so a due-date/recency window can't shift between the count and
    the filtered list it links to.
    """
    if kpi == "due_soon":
        thirty_days = now + timedelta(days=DUE_SOON_DEFAULT_DAYS)
        stmt = stmt.where(
            Opportunity.proposal_due_at.isnot(None),
            Opportunity.proposal_due_at >= now,
            Opportunity.proposal_due_at <= thirty_days,
        )
    elif kpi == "awaiting_go_no_go":
        stmt = stmt.where(awaiting_go_no_go_clause())
    elif kpi == "active_proposals":
        stmt = stmt.where(Opportunity.pipeline_stage_id.in_(_stage_id_subquery(ACTIVE_PROPOSAL_STAGE_NAMES)))
    elif kpi == "interviews_pending":
        stmt = stmt.where(Opportunity.pipeline_stage_id.in_(_stage_id_subquery(STAGE_INTERVIEW)))
    elif kpi == "awards_pending":
        stmt = stmt.where(Opportunity.pipeline_stage_id.in_(_stage_id_subquery(STAGE_AWARD_PENDING)))
    elif kpi == "sdvosb":
        stmt = stmt.where(Opportunity.is_sdvosb_setaside.is_(True))
    elif kpi == "limited_competition":
        stmt = stmt.where(Opportunity.set_aside != SetAsideType.UNRESTRICTED)
    elif kpi == "recompete":
        stmt = stmt.where(Opportunity.incumbent_company_id.isnot(None))
    elif kpi == "early_stage":
        stmt = stmt.where(Opportunity.maturity_stage.in_(EARLY_STAGES))
    elif kpi == "discovered_this_week":
        stmt = stmt.where(Opportunity.created_at >= now - timedelta(days=DISCOVERED_RECENTLY_DAYS))
    return stmt
