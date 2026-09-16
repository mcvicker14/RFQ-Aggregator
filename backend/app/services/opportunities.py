from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import ActivityType, SetAsideType
from app.models.intelligence import IntelligenceItem
from app.models.opportunity import Opportunity
from app.models.pipeline import PipelineStage
from app.models.user import User
from app.schemas.opportunity import OpportunityCreate, OpportunityUpdate
from app.services.activities import log_activity
from app.services.intelligence_sync import SYNCABLE_FIELDS
from app.services.scoring import calculate_score


def _default_stage(db: Session) -> PipelineStage | None:
    return db.execute(
        select(PipelineStage).where(PipelineStage.name == "Signal Detected")
    ).scalars().first()


def create_opportunity(db: Session, data: OpportunityCreate, created_by: User) -> Opportunity:
    payload = data.model_dump()
    source_item_id = payload.pop("source_intelligence_item_id", None)
    if payload.get("pipeline_stage_id") is None:
        stage = _default_stage(db)
        payload["pipeline_stage_id"] = stage.id if stage else None

    opp = Opportunity(**payload, created_by_id=created_by.id, is_sample_data=False)
    opp.is_sdvosb_setaside = opp.set_aside == SetAsideType.SDVOSB
    db.add(opp)
    db.flush()

    if source_item_id is not None:
        source_item = db.get(IntelligenceItem, source_item_id)
        if source_item is not None:
            source_item.opportunity_id = opp.id

    log_activity(db, opp.id, ActivityType.CREATED, f"Opportunity created by {created_by.full_name}", actor_id=created_by.id)
    calculate_score(db, opp)
    db.commit()
    db.refresh(opp)
    return opp


def update_opportunity(db: Session, opp: Opportunity, data: OpportunityUpdate, actor: User) -> Opportunity:
    updates = data.model_dump(exclude_unset=True)
    stage_changed = "pipeline_stage_id" in updates and updates["pipeline_stage_id"] != opp.pipeline_stage_id
    old_stage_id = opp.pipeline_stage_id

    rescore_needed = False
    for field_name, value in updates.items():
        if getattr(opp, field_name) == value:
            continue
        setattr(opp, field_name, value)
        if field_name in SYNCABLE_FIELDS:
            # A human is now the authority on this field — ingestion will not overwrite it.
            if field_name not in opp.locked_fields:
                opp.locked_fields = [*opp.locked_fields, field_name]
        if field_name == "set_aside":
            opp.is_sdvosb_setaside = value == SetAsideType.SDVOSB
        rescore_needed = True

    if stage_changed:
        old_stage = db.get(PipelineStage, old_stage_id) if old_stage_id else None
        new_stage = db.get(PipelineStage, opp.pipeline_stage_id) if opp.pipeline_stage_id else None
        log_activity(
            db, opp.id, ActivityType.STAGE_CHANGED,
            f"Stage changed from '{old_stage.name if old_stage else 'None'}' to '{new_stage.name if new_stage else 'None'}'",
            actor_id=actor.id,
        )
    elif updates:
        log_activity(
            db, opp.id, ActivityType.FIELD_UPDATED,
            f"{actor.full_name} updated {', '.join(updates.keys())}",
            actor_id=actor.id,
        )

    db.flush()
    if rescore_needed:
        calculate_score(db, opp)
    db.commit()
    db.refresh(opp)
    return opp


def change_stage(db: Session, opp: Opportunity, new_stage_id: UUID, actor: User, note: str | None = None) -> Opportunity:
    old_stage = db.get(PipelineStage, opp.pipeline_stage_id) if opp.pipeline_stage_id else None
    new_stage = db.get(PipelineStage, new_stage_id)
    opp.pipeline_stage_id = new_stage_id
    description = f"Stage changed from '{old_stage.name if old_stage else 'None'}' to '{new_stage.name if new_stage else 'None'}'"
    log_activity(db, opp.id, ActivityType.STAGE_CHANGED, description, detail=note, actor_id=actor.id)
    db.commit()
    db.refresh(opp)
    return opp


def get_intelligence_timeline(db: Session, opportunity_id: UUID) -> list[IntelligenceItem]:
    """Every intelligence item that fed into this opportunity, across every source
    that reported it — items promoted directly into it, plus any other item sharing a
    dedup cluster with one of those (e.g. an early signal spotted weeks before the
    live solicitation it turned out to be), sorted oldest-first. See
    docs/PHASE2_ARCHITECTURE.md §4/§11."""
    direct_items = db.execute(
        select(IntelligenceItem).where(IntelligenceItem.opportunity_id == opportunity_id)
    ).scalars().all()

    by_id = {item.id: item for item in direct_items}
    cluster_ids = {item.project_cluster_id for item in direct_items if item.project_cluster_id}
    if cluster_ids:
        clustered_items = db.execute(
            select(IntelligenceItem).where(IntelligenceItem.project_cluster_id.in_(cluster_ids))
        ).scalars().all()
        for item in clustered_items:
            by_id[item.id] = item

    return sorted(by_id.values(), key=lambda item: item.first_detected_at)
