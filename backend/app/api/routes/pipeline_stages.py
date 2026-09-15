from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.pipeline import PipelineStage
from app.models.user import User
from app.schemas.reference import PipelineStageRead, PipelineStageUpdate

router = APIRouter(prefix="/api/pipeline-stages", tags=["pipeline"])


@router.get("", response_model=list[PipelineStageRead])
def list_stages(db: Session = Depends(get_db), _current: User = Depends(get_current_user)):
    return db.execute(select(PipelineStage).order_by(PipelineStage.sort_order)).scalars().all()


@router.patch("", response_model=list[PipelineStageRead])
def update_stages(updates: list[PipelineStageUpdate], db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    for update in updates:
        stage = db.get(PipelineStage, update.id)
        if stage is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Pipeline stage {update.id} not found")
        for field_name, value in update.model_dump(exclude_unset=True, exclude={"id"}).items():
            setattr(stage, field_name, value)
    db.commit()
    return db.execute(select(PipelineStage).order_by(PipelineStage.sort_order)).scalars().all()
