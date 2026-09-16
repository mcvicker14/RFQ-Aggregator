from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import IntelligenceCategory, JurisdictionLevel, MaturityStage, SetAsideType
from app.models.intelligence import IntelligenceItem
from app.models.scoring import OpportunityScore
from app.models.user import User
from app.schemas.intelligence import IntelligenceItemRead
from app.services.sam_relevance_scoring import (
    HIGHLY_RELEVANT_THRESHOLD,
    POSSIBLE_MATCH_THRESHOLD,
    RELEVANT_THRESHOLD,
)

router = APIRouter(prefix="/api/intelligence", tags=["intelligence-items"])

# OpportunityScore keeps a full history (a new row each recalculation — see
# docs/SCORING_METHODOLOGY.md), so this is "the current Principal Pursuit Score":
# one row per opportunity, the most recently computed. Postgres DISTINCT ON, ordered
# to match, picks it in one query rather than the N+1 a naive per-item lookup would be.
_latest_pursuit_score = (
    select(OpportunityScore.opportunity_id, OpportunityScore.score)
    .distinct(OpportunityScore.opportunity_id)
    .order_by(OpportunityScore.opportunity_id, OpportunityScore.computed_at.desc())
    .subquery()
)

_SORT_COLUMNS = {
    "first_detected_at": IntelligenceItem.first_detected_at,
    "proposal_due_at": IntelligenceItem.proposal_due_at,
    "estimated_value_high": IntelligenceItem.estimated_value_high,
    "funding_amount": IntelligenceItem.funding_amount,
    "early_signal_score": IntelligenceItem.early_signal_score,
    "sam_relevance_score": IntelligenceItem.sam_relevance_score,
    "pursuit_score": _latest_pursuit_score.c.score,
}

# Mirrors sam_relevance_scoring.py's tier boundaries exactly — imported rather than
# redefined so the API's default view can never silently drift out of sync with the
# scoring engine's own definition of each tier.
_SAM_RELEVANCE_TIER_FLOOR: dict[str, int | None] = {
    "highly_relevant": HIGHLY_RELEVANT_THRESHOLD,
    "relevant": RELEVANT_THRESHOLD,
    "possible_match": POSSIBLE_MATCH_THRESHOLD,
    "all": None,
}


@router.get("/items", response_model=list[IntelligenceItemRead])
def list_intelligence_items(
    db: Session = Depends(get_db),
    _current: User = Depends(get_current_user),
    q: str | None = Query(None, description="Free-text search across title, agency, location"),
    category: IntelligenceCategory | None = None,
    source_id: UUID | None = None,
    jurisdiction_level: JurisdictionLevel | None = None,
    agency_id: UUID | None = None,
    state: str | None = None,
    naics_code: str | None = None,
    maturity_stage: MaturityStage | None = None,
    set_aside: SetAsideType | None = None,
    include_sample_data: bool = True,
    unpromoted_only: bool = Query(False, description="Only items not yet linked to an Opportunity"),
    sam_relevance_tier: str = Query(
        "relevant",
        pattern="^(highly_relevant|relevant|possible_match|all)$",
        description=(
            "Default Discover view is 'relevant' (SAM Relevance Score >= 65) and "
            "above, for SAM.gov items only — this never hides items from any other "
            "source, which has no SAM relevance score to filter on at all. "
            "'possible_match' widens to >=50, 'all' removes the filter entirely."
        ),
    ),
    sort_by: str = Query(
        "first_detected_at",
        pattern="^(first_detected_at|proposal_due_at|estimated_value_high|funding_amount|early_signal_score|sam_relevance_score|pursuit_score)$",
    ),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    stmt = select(IntelligenceItem)
    if sort_by == "pursuit_score":
        # Only joined when actually needed for ordering — every other sort avoids the
        # extra join. LEFT (not inner): an unpromoted item still has to appear, just
        # sorted as if it has no score (see the NULLs-last handling below).
        stmt = stmt.outerjoin(
            _latest_pursuit_score, IntelligenceItem.opportunity_id == _latest_pursuit_score.c.opportunity_id
        )

    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                IntelligenceItem.title.ilike(like),
                IntelligenceItem.agency_name.ilike(like),
                IntelligenceItem.location_city.ilike(like),
                IntelligenceItem.solicitation_number.ilike(like),
            )
        )
    if category:
        stmt = stmt.where(IntelligenceItem.intelligence_category == category)
    if source_id:
        stmt = stmt.where(IntelligenceItem.intelligence_source_id == source_id)
    if jurisdiction_level:
        stmt = stmt.where(IntelligenceItem.jurisdiction_level == jurisdiction_level)
    if agency_id:
        stmt = stmt.where(IntelligenceItem.agency_id == agency_id)
    if state:
        stmt = stmt.where(IntelligenceItem.location_state == state.upper())
    if naics_code:
        stmt = stmt.where(IntelligenceItem.naics_code == naics_code)
    if maturity_stage:
        stmt = stmt.where(IntelligenceItem.maturity_stage == maturity_stage)
    if set_aside:
        stmt = stmt.where(IntelligenceItem.set_aside == set_aside)
    if not include_sample_data:
        stmt = stmt.where(IntelligenceItem.is_sample_data.is_(False))
    if unpromoted_only:
        stmt = stmt.where(IntelligenceItem.opportunity_id.is_(None))

    floor = _SAM_RELEVANCE_TIER_FLOOR[sam_relevance_tier]
    if floor is not None:
        stmt = stmt.where(
            or_(IntelligenceItem.sam_relevance_score.is_(None), IntelligenceItem.sam_relevance_score >= floor)
        )

    column = _SORT_COLUMNS[sort_by]
    order = column.desc() if sort_dir == "desc" else column.asc()
    # NULLs sort last regardless of direction — a missing due date/score shouldn't
    # bury real, orderable values from the sorted end the user asked for, nor should
    # it come first and look like the most urgent/highest-scoring result.
    stmt = stmt.order_by(column.is_(None), order).limit(limit).offset(offset)

    items = db.execute(stmt).scalars().all()

    # pursuit_score isn't an IntelligenceItem column (see the schema's own comment) —
    # populated here, for every returned item regardless of sort_by, so Discover can
    # always display it. One batched query, not N+1.
    promoted_ids = [item.opportunity_id for item in items if item.opportunity_id]
    scores_by_opportunity_id: dict = {}
    if promoted_ids:
        rows = db.execute(
            select(_latest_pursuit_score.c.opportunity_id, _latest_pursuit_score.c.score).where(
                _latest_pursuit_score.c.opportunity_id.in_(promoted_ids)
            )
        ).all()
        scores_by_opportunity_id = dict(rows)
    for item in items:
        item.pursuit_score = scores_by_opportunity_id.get(item.opportunity_id)

    return items
