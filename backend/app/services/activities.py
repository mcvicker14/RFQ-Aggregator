from uuid import UUID

from sqlalchemy.orm import Session

from app.models.activity import Activity
from app.models.enums import ActivityType


def log_activity(
    db: Session,
    opportunity_id: UUID,
    activity_type: ActivityType,
    description: str,
    detail: str | None = None,
    extra_data: dict | None = None,
    actor_id: UUID | None = None,
) -> Activity:
    activity = Activity(
        opportunity_id=opportunity_id,
        activity_type=activity_type,
        description=description,
        detail=detail,
        extra_data=extra_data,
        actor_id=actor_id,
    )
    db.add(activity)
    db.flush()
    return activity
