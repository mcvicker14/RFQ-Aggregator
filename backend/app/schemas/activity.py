from datetime import datetime
from uuid import UUID

from app.models.enums import ActivityType
from app.schemas.common import ORMModel


class ActivityRead(ORMModel):
    id: UUID
    opportunity_id: UUID
    activity_type: ActivityType
    description: str
    detail: str | None
    extra_data: dict | None
    actor_id: UUID | None
    created_at: datetime
