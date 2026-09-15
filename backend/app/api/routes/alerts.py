from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.alert import Alert, AlertRule
from app.models.enums import AlertCategory
from app.models.user import User
from app.schemas.alert import AlertRead, AlertRuleRead, AlertRuleUpdate

router = APIRouter(tags=["alerts"])


@router.get("/api/alerts", response_model=list[AlertRead])
def list_alerts(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    unread_only: bool = Query(False),
):
    stmt = select(Alert).where(or_(Alert.user_id == current_user.id, Alert.user_id.is_(None)))
    if unread_only:
        stmt = stmt.where(Alert.is_read.is_(False))
    return db.execute(stmt.order_by(Alert.created_at.desc()).limit(200)).scalars().all()


@router.patch("/api/alerts/{alert_id}/read", response_model=AlertRead)
def mark_read(alert_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    alert.is_read = True
    db.commit()
    db.refresh(alert)
    return alert


@router.get("/api/alert-rules", response_model=list[AlertRuleRead])
def list_alert_rules(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    existing = db.execute(select(AlertRule).where(AlertRule.user_id == current_user.id)).scalars().all()
    existing_categories = {r.category for r in existing}
    for category in AlertCategory:
        if category not in existing_categories:
            db.add(AlertRule(user_id=current_user.id, category=category, is_enabled=True))
    db.commit()
    return db.execute(select(AlertRule).where(AlertRule.user_id == current_user.id)).scalars().all()


@router.patch("/api/alert-rules/{rule_id}", response_model=AlertRuleRead)
def update_alert_rule(
    rule_id: UUID, payload: AlertRuleUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    rule = db.get(AlertRule, rule_id)
    if rule is None or rule.user_id != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert rule not found")
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(rule, field_name, value)
    db.commit()
    db.refresh(rule)
    return rule
