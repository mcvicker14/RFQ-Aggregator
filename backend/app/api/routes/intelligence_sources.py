from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin, require_bd_or_above
from app.db.session import get_db
from app.models.enums import SyncTriggeredBy
from app.models.intelligence import IntelligenceSource, IntelligenceSyncRun
from app.models.user import User
from app.schemas.intelligence import (
    IntelligenceSourceRead,
    IntelligenceSourceUpdate,
    IntelligenceSyncRunRead,
    SyncAllResult,
)
from app.services.intelligence_sync import SyncAlreadyRunningError, run_sync

router = APIRouter(prefix="/api/intelligence", tags=["intelligence-sources"])


def _get_source_or_404(db: Session, source_id: UUID) -> IntelligenceSource:
    source = db.get(IntelligenceSource, source_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intelligence source not found")
    return source


@router.get("/sources", response_model=list[IntelligenceSourceRead])
def list_sources(db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    return db.execute(select(IntelligenceSource).order_by(IntelligenceSource.name)).scalars().all()


@router.patch("/sources/{source_id}", response_model=IntelligenceSourceRead)
def update_source(
    source_id: UUID, payload: IntelligenceSourceUpdate,
    db: Session = Depends(get_db), _admin: User = Depends(require_admin),
):
    source = _get_source_or_404(db, source_id)
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(source, field_name, value)
    db.commit()
    db.refresh(source)
    return source


@router.post("/sources/{source_id}/sync", response_model=IntelligenceSyncRunRead)
def sync_source(
    source_id: UUID, db: Session = Depends(get_db), current: User = Depends(require_bd_or_above),
):
    source = _get_source_or_404(db, source_id)
    try:
        return run_sync(db, source, SyncTriggeredBy.MANUAL, triggered_by_user_id=current.id)
    except SyncAlreadyRunningError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/sync-all", response_model=SyncAllResult)
def sync_all_enabled_sources(db: Session = Depends(get_db), current: User = Depends(require_bd_or_above)):
    sources = db.execute(
        select(IntelligenceSource).where(
            IntelligenceSource.is_enabled.is_(True), IntelligenceSource.connector_key.isnot(None)
        )
    ).scalars().all()

    attempted = succeeded = 0
    skipped: list[str] = []
    for source in sources:
        attempted += 1
        try:
            run = run_sync(db, source, SyncTriggeredBy.MANUAL, triggered_by_user_id=current.id)
            if run.status.value != "failure":
                succeeded += 1
            else:
                skipped.append(f"{source.name} (sync failed — see sync history)")
        except SyncAlreadyRunningError:
            skipped.append(f"{source.name} (already syncing)")
        except ValueError as exc:
            skipped.append(f"{source.name} ({exc})")

    return SyncAllResult(sources_attempted=attempted, sources_succeeded=succeeded, sources_skipped=skipped)


@router.get("/sync-runs", response_model=list[IntelligenceSyncRunRead])
def list_sync_runs(
    source_id: UUID | None = None, limit: int = 50,
    db: Session = Depends(get_db), _current: User = Depends(get_current_user),
):
    query = select(IntelligenceSyncRun).order_by(IntelligenceSyncRun.started_at.desc()).limit(min(limit, 200))
    if source_id is not None:
        query = query.where(IntelligenceSyncRun.intelligence_source_id == source_id)
    return db.execute(query).scalars().all()
