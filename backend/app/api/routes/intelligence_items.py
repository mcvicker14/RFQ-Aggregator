from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import IntelligenceCategory, JurisdictionLevel, MaturityStage, SetAsideType
from app.models.intelligence import IntelligenceItem
from app.models.user import User
from app.schemas.intelligence import IntelligenceItemRead

router = APIRouter(prefix="/api/intelligence", tags=["intelligence-items"])

_SORT_COLUMNS = {
    "first_detected_at": IntelligenceItem.first_detected_at,
    "proposal_due_at": IntelligenceItem.proposal_due_at,
    "estimated_value_high": IntelligenceItem.estimated_value_high,
    "funding_amount": IntelligenceItem.funding_amount,
    "early_signal_score": IntelligenceItem.early_signal_score,
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
    sort_by: str = Query("first_detected_at", pattern="^(first_detected_at|proposal_due_at|estimated_value_high|funding_amount|early_signal_score)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    stmt = select(IntelligenceItem)

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

    column = _SORT_COLUMNS[sort_by]
    order = column.desc() if sort_dir == "desc" else column.asc()
    # NULLs sort last regardless of direction — a missing due date/score shouldn't
    # bury real, orderable values from the sorted end the user asked for, nor should
    # it come first and look like the most urgent/highest-scoring result.
    stmt = stmt.order_by(column.is_(None), order).limit(limit).offset(offset)

    return db.execute(stmt).scalars().all()
