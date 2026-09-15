from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_bd_or_above
from app.db.session import get_db
from app.models.opportunity import Opportunity
from app.models.winloss import WinLossReview
from app.models.user import User
from app.schemas.winloss import WinLossReviewCreate, WinLossReviewRead

router = APIRouter(tags=["win-loss"])


@router.get("/api/opportunities/{opportunity_id}/win-loss", response_model=WinLossReviewRead | None)
def get_win_loss(opportunity_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    return db.execute(
        select(WinLossReview).where(WinLossReview.opportunity_id == opportunity_id)
    ).scalars().first()


@router.post("/api/opportunities/{opportunity_id}/win-loss", response_model=WinLossReviewRead, status_code=status.HTTP_201_CREATED)
def create_win_loss(
    opportunity_id: UUID,
    payload: WinLossReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_bd_or_above),
):
    if db.get(Opportunity, opportunity_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Opportunity not found")

    review = db.execute(select(WinLossReview).where(WinLossReview.opportunity_id == opportunity_id)).scalars().first()
    if review is None:
        review = WinLossReview(opportunity_id=opportunity_id)
        db.add(review)

    for field_name, value in payload.model_dump().items():
        setattr(review, field_name, value)
    review.recorded_by_id = current_user.id

    db.commit()
    db.refresh(review)
    return review
