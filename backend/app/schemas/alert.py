from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import AlertCategory
from app.schemas.common import ORMModel


class AlertRead(ORMModel):
    id: UUID
    category: AlertCategory
    title: str
    body: str | None
    opportunity_id: UUID | None
    is_read: bool
    created_at: datetime


class AlertRuleRead(ORMModel):
    id: UUID
    category: AlertCategory
    is_enabled: bool
    filters: dict | None
    deliver_in_app: bool
    deliver_email: bool


class AlertRuleUpdate(BaseModel):
    is_enabled: bool | None = None
    filters: dict | None = None
    deliver_in_app: bool | None = None
    deliver_email: bool | None = None
