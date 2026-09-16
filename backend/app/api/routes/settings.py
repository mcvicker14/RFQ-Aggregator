from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.scoring import ScoringWeightProfile
from app.models.user import User
from app.schemas.scoring import ScoringWeightProfileRead, ScoringWeightProfileUpdate
from app.services.app_settings import HIDE_SAMPLE_DATA_KEY, hide_sample_data_by_default, set_setting

router = APIRouter(prefix="/api/settings", tags=["settings"])


class HideSampleDataSetting(BaseModel):
    hide_sample_data_by_default: bool


@router.get("/hide-sample-data", response_model=HideSampleDataSetting)
def get_hide_sample_data(db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    return HideSampleDataSetting(hide_sample_data_by_default=hide_sample_data_by_default(db))


@router.patch("/hide-sample-data", response_model=HideSampleDataSetting)
def update_hide_sample_data(
    payload: HideSampleDataSetting, db: Session = Depends(get_db), admin: User = Depends(require_admin)
):
    set_setting(db, HIDE_SAMPLE_DATA_KEY, payload.hide_sample_data_by_default, admin.id)
    return payload


def _active_profile(db: Session) -> ScoringWeightProfile:
    profile = db.execute(select(ScoringWeightProfile).where(ScoringWeightProfile.is_active.is_(True))).scalars().first()
    if profile is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "No active scoring weight profile configured")
    return profile


@router.get("/scoring-weights", response_model=ScoringWeightProfileRead)
def get_scoring_weights(db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    return _active_profile(db)


@router.patch("/scoring-weights", response_model=ScoringWeightProfileRead)
def update_scoring_weights(
    payload: ScoringWeightProfileUpdate, db: Session = Depends(get_db), _admin: User = Depends(require_admin)
):
    profile = _active_profile(db)
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field_name, value)
    db.commit()
    db.refresh(profile)
    return profile
