from datetime import date
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import TaskPriority, TaskStatus
from app.schemas.common import ORMModel


class TaskBase(BaseModel):
    title: str
    notes: str | None = None
    owner_id: UUID | None = None
    due_date: date | None = None
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.OPEN


class TaskCreate(TaskBase):
    opportunity_id: UUID | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    notes: str | None = None
    owner_id: UUID | None = None
    due_date: date | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None


class TaskRead(TaskBase, ORMModel):
    id: UUID
    opportunity_id: UUID | None
    opportunity_title: str | None = None
    created_by_id: UUID | None
