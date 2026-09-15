from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import ActivityType, TaskStatus
from app.models.opportunity import Opportunity
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services.activities import log_activity

router = APIRouter(tags=["tasks"])


def _to_read(task: Task, title_by_opp: dict[UUID, str]) -> TaskRead:
    return TaskRead(
        id=task.id, opportunity_id=task.opportunity_id,
        opportunity_title=title_by_opp.get(task.opportunity_id) if task.opportunity_id else None,
        title=task.title, notes=task.notes, owner_id=task.owner_id, due_date=task.due_date,
        priority=task.priority, status=task.status, created_by_id=task.created_by_id,
    )


@router.get("/api/tasks", response_model=list[TaskRead])
def list_tasks(
    db: Session = Depends(get_db),
    _current: User = Depends(get_current_user),
    status_filter: TaskStatus | None = Query(None, alias="status"),
    owner_id: UUID | None = None,
    opportunity_id: UUID | None = None,
):
    stmt = select(Task)
    if status_filter:
        stmt = stmt.where(Task.status == status_filter)
    if owner_id:
        stmt = stmt.where(Task.owner_id == owner_id)
    if opportunity_id:
        stmt = stmt.where(Task.opportunity_id == opportunity_id)
    tasks = db.execute(stmt.order_by(Task.due_date.asc().nulls_last())).scalars().all()

    opp_ids = {t.opportunity_id for t in tasks if t.opportunity_id}
    titles = {
        o.id: o.title for o in db.execute(select(Opportunity).where(Opportunity.id.in_(opp_ids))).scalars().all()
    } if opp_ids else {}
    return [_to_read(t, titles) for t in tasks]


@router.get("/api/opportunities/{opportunity_id}/tasks", response_model=list[TaskRead])
def list_opportunity_tasks(opportunity_id: UUID, db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    tasks = db.execute(
        select(Task).where(Task.opportunity_id == opportunity_id).order_by(Task.due_date.asc().nulls_last())
    ).scalars().all()
    opp = db.get(Opportunity, opportunity_id)
    titles = {opportunity_id: opp.title} if opp else {}
    return [_to_read(t, titles) for t in tasks]


@router.post("/api/opportunities/{opportunity_id}/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_opportunity_task(
    opportunity_id: UUID, payload: TaskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)
):
    return _create_task(db, payload, current_user, opportunity_id_override=opportunity_id)


@router.post("/api/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _create_task(db, payload, current_user)


def _create_task(db: Session, payload: TaskCreate, current_user: User, opportunity_id_override: UUID | None = None) -> TaskRead:
    data = payload.model_dump()
    if opportunity_id_override:
        data["opportunity_id"] = opportunity_id_override
    task = Task(**data, created_by_id=current_user.id)
    db.add(task)
    db.flush()
    if task.opportunity_id:
        log_activity(db, task.opportunity_id, ActivityType.TASK_CREATED, f"Task created: {task.title}", actor_id=current_user.id)
    db.commit()
    db.refresh(task)
    opp = db.get(Opportunity, task.opportunity_id) if task.opportunity_id else None
    return _to_read(task, {task.opportunity_id: opp.title} if opp else {})


@router.patch("/api/tasks/{task_id}", response_model=TaskRead)
def update_task(task_id: UUID, payload: TaskUpdate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")

    updates = payload.model_dump(exclude_unset=True)
    was_completed = task.status == TaskStatus.COMPLETED
    for field_name, value in updates.items():
        setattr(task, field_name, value)

    if task.opportunity_id and not was_completed and task.status == TaskStatus.COMPLETED:
        log_activity(db, task.opportunity_id, ActivityType.TASK_COMPLETED, f"Task completed: {task.title}", actor_id=current_user.id)

    db.commit()
    db.refresh(task)
    opp = db.get(Opportunity, task.opportunity_id) if task.opportunity_id else None
    return _to_read(task, {task.opportunity_id: opp.title} if opp else {})
