from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_bd_or_above
from app.db.session import get_db
from app.models.agency import Agency, AgencyOffice
from app.models.user import User
from app.schemas.agency import AgencyCreate, AgencyOfficeCreate, AgencyOfficeRead, AgencyRead, AgencyUpdate

router = APIRouter(prefix="/api/agencies", tags=["agencies"])


@router.get("", response_model=list[AgencyRead])
def list_agencies(db: Session = Depends(get_db), _current: User = Depends(get_current_user), q: str | None = Query(None)):
    stmt = select(Agency)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Agency.name.ilike(like), Agency.short_name.ilike(like)))
    return db.execute(stmt.order_by(Agency.priority_tier, Agency.name)).scalars().all()


@router.post("", response_model=AgencyRead, status_code=status.HTTP_201_CREATED)
def create_agency(payload: AgencyCreate, db: Session = Depends(get_db), _current: User = Depends(require_bd_or_above)):
    agency = Agency(**payload.model_dump())
    db.add(agency)
    db.commit()
    db.refresh(agency)
    return agency


@router.get("/{agency_id}", response_model=AgencyRead)
def get_agency(agency_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    agency = db.get(Agency, agency_id)
    if agency is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agency not found")
    return agency


@router.patch("/{agency_id}", response_model=AgencyRead)
def update_agency(
    agency_id: UUID, payload: AgencyUpdate, db: Session = Depends(get_db), _current: User = Depends(require_bd_or_above)
):
    agency = db.get(Agency, agency_id)
    if agency is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agency not found")
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(agency, field_name, value)
    db.commit()
    db.refresh(agency)
    return agency


@router.post("/{agency_id}/offices", response_model=AgencyOfficeRead, status_code=status.HTTP_201_CREATED)
def create_office(
    agency_id: UUID, payload: AgencyOfficeCreate, db: Session = Depends(get_db), _current: User = Depends(require_bd_or_above)
):
    if db.get(Agency, agency_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agency not found")
    office = AgencyOffice(agency_id=agency_id, **payload.model_dump())
    db.add(office)
    db.commit()
    db.refresh(office)
    return office
