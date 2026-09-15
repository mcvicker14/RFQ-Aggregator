from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_bd_or_above
from app.db.session import get_db
from app.models.company import Company, OpportunityCompany
from app.models.enums import CompanyType
from app.models.user import User
from app.schemas.company import CompanyCreate, CompanyRead, CompanyUpdate, OpportunityCompanyCreate, OpportunityCompanyRead

router = APIRouter(tags=["companies"])


@router.get("/api/companies", response_model=list[CompanyRead])
def list_companies(
    db: Session = Depends(get_db),
    _current: User = Depends(get_current_user),
    q: str | None = Query(None),
    company_type: CompanyType | None = None,
    is_sdvosb: bool | None = None,
):
    stmt = select(Company)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Company.name.ilike(like), Company.technical_specialties.ilike(like), Company.agencies_served.ilike(like)))
    if company_type:
        stmt = stmt.where(Company.company_type == company_type)
    if is_sdvosb is not None:
        stmt = stmt.where(Company.is_sdvosb == is_sdvosb)
    return db.execute(stmt.order_by(Company.name)).scalars().all()


@router.post("/api/companies", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db), _current: User = Depends(require_bd_or_above)):
    company = Company(**payload.model_dump(), is_sample_data=False)
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@router.get("/api/companies/{company_id}", response_model=CompanyRead)
def get_company(company_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return company


@router.patch("/api/companies/{company_id}", response_model=CompanyRead)
def update_company(
    company_id: UUID, payload: CompanyUpdate, db: Session = Depends(get_db), _current: User = Depends(require_bd_or_above)
):
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, field_name, value)
    db.commit()
    db.refresh(company)
    return company


@router.get("/api/opportunities/{opportunity_id}/companies", response_model=list[OpportunityCompanyRead])
def list_opportunity_companies(opportunity_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    return db.execute(
        select(OpportunityCompany).where(OpportunityCompany.opportunity_id == opportunity_id)
    ).scalars().all()


@router.post(
    "/api/opportunities/{opportunity_id}/companies",
    response_model=OpportunityCompanyRead,
    status_code=status.HTTP_201_CREATED,
)
def link_company_to_opportunity(
    opportunity_id: UUID,
    payload: OpportunityCompanyCreate,
    db: Session = Depends(get_db),
    _current: User = Depends(require_bd_or_above),
):
    if db.get(Company, payload.company_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    link = OpportunityCompany(opportunity_id=opportunity_id, **payload.model_dump())
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.delete("/api/opportunity-companies/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_company(link_id: UUID, db: Session = Depends(get_db), _current: User = Depends(require_bd_or_above)):
    link = db.get(OpportunityCompany, link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    db.delete(link)
    db.commit()
