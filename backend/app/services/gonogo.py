from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.enums import ActivityType, GoNoGoOutcome
from app.models.gonogo import DEFAULT_GONOGO_CRITERIA, GoNoGoCriteriaScore, GoNoGoReview
from app.models.user import User
from app.schemas.gonogo import GoNoGoCriteriaScoreUpsert
from app.services.activities import log_activity


def get_or_create_review(db: Session, opportunity_id: UUID) -> GoNoGoReview:
    review = db.execute(
        select(GoNoGoReview).where(GoNoGoReview.opportunity_id == opportunity_id)
    ).scalars().first()
    if review:
        return review

    review = GoNoGoReview(opportunity_id=opportunity_id)
    db.add(review)
    db.flush()
    for criterion in DEFAULT_GONOGO_CRITERIA:
        db.add(GoNoGoCriteriaScore(review_id=review.id, criterion=criterion, score=3))
    db.flush()
    log_activity(db, opportunity_id, ActivityType.GONOGO_STARTED, "Go/No-Go review started")
    db.commit()
    db.refresh(review)
    return review


def _recompute_ai_recommendation(review: GoNoGoReview) -> None:
    scores = [c.score for c in review.criteria_scores]
    if not scores:
        review.ai_recommendation = None
        review.ai_recommendation_rationale = None
        return

    avg = sum(scores) / len(scores)
    if avg >= 4.0:
        review.ai_recommendation = GoNoGoOutcome.GO.value
    elif avg >= 2.5:
        review.ai_recommendation = GoNoGoOutcome.CONDITIONAL_GO.value
    else:
        review.ai_recommendation = GoNoGoOutcome.NO_GO.value

    weakest = sorted(review.criteria_scores, key=lambda c: c.score)[:3]
    weak_text = "; ".join(f"{c.criterion} ({c.score}/5)" for c in weakest if c.score <= 3)
    review.ai_recommendation_rationale = (
        f"Average criteria score {avg:.1f}/5 across {len(scores)} criteria."
        + (f" Weakest areas: {weak_text}." if weak_text else " No notably weak criteria.")
        + " This is an advisory recommendation only — a named decision-maker must record the actual Go/No-Go."
    )


def upsert_criteria_scores(
    db: Session, review: GoNoGoReview, scores: list[GoNoGoCriteriaScoreUpsert]
) -> GoNoGoReview:
    existing_by_criterion = {c.criterion: c for c in review.criteria_scores}
    for item in scores:
        row = existing_by_criterion.get(item.criterion)
        if row:
            row.score = item.score
            row.notes = item.notes
        else:
            db.add(GoNoGoCriteriaScore(review_id=review.id, criterion=item.criterion, score=item.score, notes=item.notes))
    db.flush()
    db.refresh(review)
    _recompute_ai_recommendation(review)
    db.commit()
    db.refresh(review)
    return review


def record_decision(
    db: Session, review: GoNoGoReview, decision: GoNoGoOutcome, notes: str | None, decided_by: User
) -> GoNoGoReview:
    review.decision = decision
    review.decided_by_id = decided_by.id
    review.decided_at = utcnow()
    review.decision_notes = notes
    log_activity(
        db, review.opportunity_id, ActivityType.GONOGO_DECIDED,
        f"{decided_by.full_name} recorded decision: {decision.value.upper()}",
        detail=notes, actor_id=decided_by.id,
    )
    db.commit()
    db.refresh(review)
    return review
