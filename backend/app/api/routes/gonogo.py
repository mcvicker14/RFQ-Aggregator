from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_decision_maker
from app.db.session import get_db
from app.models.gonogo import GoNoGoReview
from app.models.user import User
from app.schemas.gonogo import GoNoGoCriteriaScoreUpsert, GoNoGoDecisionRequest, GoNoGoReviewRead
from app.services import gonogo as gonogo_service

router = APIRouter(tags=["go-no-go"])


@router.get("/api/opportunities/{opportunity_id}/gonogo", response_model=GoNoGoReviewRead)
def get_review(opportunity_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    return gonogo_service.get_or_create_review(db, opportunity_id)


@router.patch("/api/gonogo/{review_id}", response_model=GoNoGoReviewRead)
def update_criteria(
    review_id: UUID,
    scores: list[GoNoGoCriteriaScoreUpsert],
    db: Session = Depends(get_db),
    _current: User = Depends(get_current_user),
):
    review = db.get(GoNoGoReview, review_id)
    if review is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Go/No-Go review not found")
    return gonogo_service.upsert_criteria_scores(db, review, scores)


@router.post("/api/gonogo/{review_id}/decide", response_model=GoNoGoReviewRead)
def decide(
    review_id: UUID,
    payload: GoNoGoDecisionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_decision_maker),
):
    review = db.get(GoNoGoReview, review_id)
    if review is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Go/No-Go review not found")
    return gonogo_service.record_decision(db, review, payload.decision, payload.decision_notes, current_user)
