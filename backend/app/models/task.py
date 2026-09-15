import uuid
from datetime import date

from sqlalchemy import Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid, pg_enum
from app.models.enums import TaskPriority, TaskStatus


class Task(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "tasks"

    opportunity_id: Mapped[uuid.UUID | None] = fk_uuid("opportunities.id", nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    owner_id: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, default=None, index=True)
    priority: Mapped[TaskPriority] = mapped_column(pg_enum(TaskPriority), default=TaskPriority.MEDIUM)
    status: Mapped[TaskStatus] = mapped_column(pg_enum(TaskStatus), default=TaskStatus.OPEN, index=True)
    created_by_id: Mapped[uuid.UUID | None] = fk_uuid("users.id", nullable=True)
