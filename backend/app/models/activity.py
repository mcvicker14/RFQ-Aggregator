import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid, pg_enum
from app.models.enums import ActivityType


class Activity(UUIDPKMixin, TimestampMixin, Base):
    """Timeline of every event associated with an opportunity, spec §6."""

    __tablename__ = "activities"

    opportunity_id: Mapped[uuid.UUID] = fk_uuid("opportunities.id")
    activity_type: Mapped[ActivityType] = mapped_column(pg_enum(ActivityType), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    extra_data: Mapped[dict | None] = mapped_column(JSONB, default=None)
    actor_id: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)  # null = system/connector generated
