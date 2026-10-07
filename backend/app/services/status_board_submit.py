"""Explicit owner's Submit decision; no Go/No-Go or opportunity mutations.

A durable attempt is saved BEFORE transport. Pending/uncertain requests are never
replayed. A positive write response and an independent full-sheet read must agree.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.models.opportunity import StatusBoardRow
from app.models.status_board_edit import StatusBoardEdit
from app.models.user import User
from app.schemas.opportunity import StatusBoardSubmitEdit, StatusBoardSubmitResult
from app.services import status_board_webhook_client as webhook
from app.services.status_board_read_sync import refresh_status_board_cache


def set_board_submit(db: Session, actor: User, edit: StatusBoardSubmitEdit) -> StatusBoardSubmitResult:
    if not get_settings().STATUS_BOARD_SUBMIT_EDITS_ENABLED:
        raise HTTPException(503, "Submit editing is not enabled yet. Use Google Sheets.")
    request_id, record_id = str(edit.request_id), str(edit.source_record_id)
    previous = db.execute(select(StatusBoardEdit).where(StatusBoardEdit.request_id == request_id)).scalar_one_or_none()
    if previous:
        return _existing(previous, actor, edit)
    matches = db.execute(select(StatusBoardRow).where(StatusBoardRow.source_record_id == record_id)).scalars().all()
    if len(matches) != 1 or matches[0].source_revision != edit.expected_revision or \
            (matches[0].submit_y_n or "") != edit.expected_submit or matches[0].is_submitted_y:
        raise HTTPException(409, "The board changed. Refresh and review before saving.")
    audit = StatusBoardEdit(request_id=request_id, actor_id=actor.id, source_record_id=record_id,
        expected_revision=edit.expected_revision, old_value=edit.expected_submit, new_value=edit.value, status="pending")
    db.add(audit)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = db.execute(select(StatusBoardEdit).where(StatusBoardEdit.request_id == request_id)).scalar_one()
        return _existing(previous, actor, edit)
    try:
        result = webhook.set_submit(edit.model_dump(mode="json"))
    except (webhook.StatusBoardWebhookError, webhook.StatusBoardWebhookNotConfiguredError):
        audit.status = "uncertain"
        db.commit()
        raise HTTPException(502, "Save could not be confirmed. Inspect Google Sheets and refresh; do not retry automatically.")
    valid_ack = result.get("ok") is True and result.get("status") == "confirmed" and \
        result.get("request_id") == request_id and result.get("source_record_id") == record_id and \
        result.get("value") == edit.value
    if not valid_ack:
        audit.status = "conflict" if result.get("error") == "conflict" else "uncertain"
        db.commit()
        refresh_status_board_cache(db)
        raise HTTPException(409 if audit.status == "conflict" else 502,
            "The sheet changed or the save is unconfirmed. Refresh and inspect Google Sheets before saving again.")
    state = refresh_status_board_cache(db)
    checked = db.execute(select(StatusBoardRow).where(StatusBoardRow.source_record_id == record_id)).scalars().all()
    if state.last_error or len(checked) != 1 or (checked[0].submit_y_n or "") != edit.value or \
            checked[0].source_revision != result.get("source_revision"):
        audit.status = "uncertain"
        db.commit()
        raise HTTPException(502, "Sheet acknowledgement received, but readback did not confirm it. Refresh and inspect Google Sheets.")
    audit.status = "confirmed"
    audit.result_revision = checked[0].source_revision
    db.commit()
    return StatusBoardSubmitResult(request_id=request_id, status="confirmed", source_record_id=record_id, value=edit.value)


def _existing(audit: StatusBoardEdit, actor: User, edit: StatusBoardSubmitEdit) -> StatusBoardSubmitResult:
    if (audit.actor_id, audit.source_record_id, audit.expected_revision, audit.old_value, audit.new_value) != \
            (actor.id, str(edit.source_record_id), edit.expected_revision, edit.expected_submit, edit.value):
        raise HTTPException(409, "Request identity was already used for a different edit.")
    if audit.status != "confirmed":
        raise HTTPException(409, "This edit was already attempted. Refresh and inspect the sheet; it will not be replayed.")
    return StatusBoardSubmitResult(request_id=audit.request_id, status="confirmed",
        source_record_id=audit.source_record_id, value=audit.new_value)
