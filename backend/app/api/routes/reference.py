from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.reference import Discipline, NaicsCode
from app.models.user import User
from app.schemas.reference import DisciplineRead, NaicsCodeRead

router = APIRouter(prefix="/api/reference", tags=["reference"])


@router.get("/naics-codes", response_model=list[NaicsCodeRead])
def list_naics_codes(db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    return db.execute(select(NaicsCode).order_by(NaicsCode.is_core_market.desc(), NaicsCode.code)).scalars().all()


@router.get("/disciplines", response_model=list[DisciplineRead])
def list_disciplines(db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    return db.execute(select(Discipline).order_by(Discipline.category, Discipline.name)).scalars().all()
