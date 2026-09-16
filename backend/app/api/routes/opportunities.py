from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_bd_or_above
from app.db.session import get_db
from app.models.agency import Agency
from app.models.enums import ActivityType, MaturityStage, OpportunityStatus, SetAsideType
from app.models.opportunity import Opportunity
from app.models.scoring import OpportunityScore
from app.models.user import User
from app.schemas.activity import ActivityRead
from app.schemas.agency import AgencyRead
from app.schemas.intelligence import IntelligenceItemRead
from app.schemas.opportunity import (
    OpportunityCreate,
    OpportunityListItem,
    OpportunityRead,
    OpportunityUpdate,
    StageChangeRequest,
)
from app.schemas.scoring import OpportunityScoreRead
from app.services import opportunities as opportunities_service
from app.services.activities import log_activity
from app.services.scoring import calculate_score

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


def _latest_score(db: Session, opportunity_id: UUID) -> OpportunityScore | None:
    return db.execute(
        select(OpportunityScore)
        .where(OpportunityScore.opportunity_id == opportunity_id)
        .order_by(OpportunityScore.computed_at.desc())
    ).scalars().first()


def _get_or_404(db: Session, opportunity_id: UUID) -> Opportunity:
    opp = db.get(Opportunity, opportunity_id)
    if opp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opportunity not found")
    return opp


@router.get("", response_model=list[OpportunityListItem])
def list_opportunities(
    db: Session = Depends(get_db),
    _current: User = Depends(get_current_user),
    q: str | None = Query(None, description="Free-text search across title, solicitation number, location"),
    stage_id: UUID | None = None,
    agency_id: UUID | None = None,
    set_aside: SetAsideType | None = None,
    state: str | None = None,
    maturity_stage: MaturityStage | None = None,
    status_filter: OpportunityStatus | None = Query(None, alias="status"),
    min_score: int | None = None,
    include_sample_data: bool = True,
    sort_by: str = Query("proposal_due_at", pattern="^(proposal_due_at|created_at|title|estimated_fee|score)$"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    stmt = select(Opportunity)
    if status_filter:
        stmt = stmt.where(Opportunity.status == status_filter)
    else:
        stmt = stmt.where(Opportunity.status == OpportunityStatus.ACTIVE)
    if not include_sample_data:
        stmt = stmt.where(Opportunity.is_sample_data.is_(False))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                Opportunity.title.ilike(like),
                Opportunity.solicitation_number.ilike(like),
                Opportunity.location_city.ilike(like),
                Opportunity.naics_code.ilike(like),
            )
        )
    if stage_id:
        stmt = stmt.where(Opportunity.pipeline_stage_id == stage_id)
    if agency_id:
        stmt = stmt.where(Opportunity.agency_id == agency_id)
    if set_aside:
        stmt = stmt.where(Opportunity.set_aside == set_aside)
    if state:
        stmt = stmt.where(Opportunity.location_state == state.upper())
    if maturity_stage:
        stmt = stmt.where(Opportunity.maturity_stage == maturity_stage)

    # Sorting and pagination happen in Python below, after scores are attached —
    # "score" isn't a column on Opportunity (it lives in opportunity_scores), so a
    # SQL-level ORDER BY + LIMIT here would paginate before that sort could apply.
    # A safety cap keeps this reasonable well beyond any realistic BD pipeline size.
    opportunities = db.execute(stmt.limit(2000)).scalars().all()
    if sort_by != "score":
        opportunities = _sort_with_nulls_last(opportunities, sort_by, sort_dir)

    agencies = {a.id: a for a in db.execute(select(Agency)).scalars().all()}
    scores = {}
    for score in db.execute(select(OpportunityScore)).scalars().all():
        existing = scores.get(score.opportunity_id)
        if existing is None or score.computed_at > existing.computed_at:
            scores[score.opportunity_id] = score

    items = [
        OpportunityListItem(
            id=o.id, title=o.title, solicitation_number=o.solicitation_number,
            location_state=o.location_state, set_aside=o.set_aside, contract_type=o.contract_type,
            estimated_value_high=o.estimated_value_high, estimated_fee=o.estimated_fee,
            proposal_due_at=o.proposal_due_at, pipeline_stage_id=o.pipeline_stage_id,
            maturity_stage=o.maturity_stage, status=o.status, is_sdvosb_setaside=o.is_sdvosb_setaside,
            is_sample_data=o.is_sample_data, agency=agencies.get(o.agency_id),
            current_score=scores[o.id].score if o.id in scores else None,
            current_score_band=scores[o.id].band if o.id in scores else None,
        )
        for o in opportunities
    ]

    if min_score is not None:
        items = [i for i in items if (i.current_score or 0) >= min_score]
    if sort_by == "score":
        items.sort(key=lambda i: i.current_score or 0, reverse=(sort_dir == "desc"))

    return items[offset : offset + limit]


_SORT_KEYS = {
    "title": lambda o: (o.title or "").lower(),
    "created_at": lambda o: o.created_at,
    "proposal_due_at": lambda o: o.proposal_due_at,
    "estimated_fee": lambda o: o.estimated_fee,
}


def _sort_with_nulls_last(opportunities: list[Opportunity], sort_by: str, sort_dir: str) -> list[Opportunity]:
    """Sorts with None values always last, regardless of direction — plain reverse=True
    on a (is_none, value) key would instead push nulls to the front on desc sorts."""
    key_fn = _SORT_KEYS[sort_by]
    with_value = [o for o in opportunities if key_fn(o) is not None]
    without_value = [o for o in opportunities if key_fn(o) is None]
    with_value.sort(key=key_fn, reverse=(sort_dir == "desc"))
    return with_value + without_value


@router.post("", response_model=OpportunityRead, status_code=status.HTTP_201_CREATED)
def create_opportunity(
    payload: OpportunityCreate, db: Session = Depends(get_db), current_user: User = Depends(require_bd_or_above)
):
    opp = opportunities_service.create_opportunity(db, payload, current_user)
    return _to_read(db, opp)


@router.get("/{opportunity_id}", response_model=OpportunityRead)
def get_opportunity(opportunity_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    opp = _get_or_404(db, opportunity_id)
    return _to_read(db, opp)


@router.get("/{opportunity_id}/intelligence-timeline", response_model=list[IntelligenceItemRead])
def get_opportunity_intelligence_timeline(
    opportunity_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)
):
    _get_or_404(db, opportunity_id)
    return opportunities_service.get_intelligence_timeline(db, opportunity_id)


@router.patch("/{opportunity_id}", response_model=OpportunityRead)
def update_opportunity(
    opportunity_id: UUID,
    payload: OpportunityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_bd_or_above),
):
    opp = _get_or_404(db, opportunity_id)
    opp = opportunities_service.update_opportunity(db, opp, payload, current_user)
    return _to_read(db, opp)


@router.delete("/{opportunity_id}", status_code=status.HTTP_204_NO_CONTENT)
def archive_opportunity(
    opportunity_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    if current_user.role.value != "administrator":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only an Administrator can archive an opportunity")
    opp = _get_or_404(db, opportunity_id)
    opp.status = OpportunityStatus.ARCHIVED
    log_activity(db, opp.id, ActivityType.FIELD_UPDATED, f"Archived by {current_user.full_name}", actor_id=current_user.id)
    db.commit()


@router.post("/{opportunity_id}/stage", response_model=OpportunityRead)
def change_stage(
    opportunity_id: UUID,
    payload: StageChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_bd_or_above),
):
    opp = _get_or_404(db, opportunity_id)
    opp = opportunities_service.change_stage(db, opp, payload.pipeline_stage_id, current_user, payload.note)
    return _to_read(db, opp)


@router.get("/{opportunity_id}/score", response_model=OpportunityScoreRead)
def get_score(opportunity_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    opp = _get_or_404(db, opportunity_id)
    score = _latest_score(db, opp.id)
    if score is None:
        score = calculate_score(db, opp)
        db.commit()
    return score


@router.post("/{opportunity_id}/score/recalculate", response_model=OpportunityScoreRead)
def recalculate_score(
    opportunity_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(require_bd_or_above)
):
    opp = _get_or_404(db, opportunity_id)
    score = calculate_score(db, opp)
    db.commit()
    return score


@router.get("/{opportunity_id}/activities", response_model=list[ActivityRead])
def list_activities(opportunity_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    from app.models.activity import Activity

    _get_or_404(db, opportunity_id)
    return db.execute(
        select(Activity).where(Activity.opportunity_id == opportunity_id).order_by(Activity.created_at.desc())
    ).scalars().all()


def _to_read(db: Session, opp: Opportunity) -> OpportunityRead:
    agency = db.get(Agency, opp.agency_id) if opp.agency_id else None
    score = _latest_score(db, opp.id)
    base = OpportunityRead.model_validate(opp).model_dump(
        exclude={"agency", "current_score", "current_score_band"}
    )
    return OpportunityRead(
        **base,
        agency=AgencyRead.model_validate(agency) if agency else None,
        current_score=score.score if score else None,
        current_score_band=score.band if score else None,
    )
