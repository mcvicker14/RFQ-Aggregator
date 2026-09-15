from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_bd_or_above
from app.db.session import get_db
from app.models.forecast import RevenueForecast
from app.models.opportunity import Opportunity
from app.models.user import User
from app.schemas.forecast import ForecastSummary, RevenueForecastRead, RevenueForecastUpsert
from app.services.forecasting import build_forecast_summary, weighted_value

router = APIRouter(tags=["forecast"])


def _to_read(fc: RevenueForecast) -> RevenueForecastRead:
    data = RevenueForecastRead.model_validate(fc).model_dump(exclude={"weighted_value"})
    return RevenueForecastRead(**data, weighted_value=weighted_value(fc))


@router.get("/api/opportunities/{opportunity_id}/forecast", response_model=RevenueForecastRead | None)
def get_forecast(opportunity_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    fc = db.execute(select(RevenueForecast).where(RevenueForecast.opportunity_id == opportunity_id)).scalars().first()
    return _to_read(fc) if fc else None


@router.post("/api/opportunities/{opportunity_id}/forecast", response_model=RevenueForecastRead)
def upsert_forecast(
    opportunity_id: UUID,
    payload: RevenueForecastUpsert,
    db: Session = Depends(get_db),
    _current: User = Depends(require_bd_or_above),
):
    opp = db.get(Opportunity, opportunity_id)
    if opp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opportunity not found")

    fc = db.execute(select(RevenueForecast).where(RevenueForecast.opportunity_id == opportunity_id)).scalars().first()
    if fc is None:
        fc = RevenueForecast(opportunity_id=opportunity_id)
        db.add(fc)

    for field_name, value in payload.model_dump().items():
        setattr(fc, field_name, value)

    db.commit()
    db.refresh(fc)
    return _to_read(fc)


@router.get("/api/forecast/summary", response_model=ForecastSummary)
def forecast_summary(
    db: Session = Depends(get_db),
    _current: User = Depends(get_current_user),
    target_period: str | None = Query(None),
):
    return build_forecast_summary(db, target_period)
