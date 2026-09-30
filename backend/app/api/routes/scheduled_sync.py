"""Scheduled-sync trigger for COREWORKS RFQwire and APEX MyBidMatch — the only two
sources with any scheduling requirement (see app/services/scheduled_sync.py for why
nothing else changes here, and the full three-layer design: this route, an in-process
APScheduler safety net in app/main.py, and an external GitHub Actions workflow).

Deliberately NOT user-JWT-authenticated (Depends(get_current_user)/require_*) — this is
called by an unattended external scheduler, not a logged-in person. Auth is a shared
secret in the request body, the same pattern app/services/status_board_webhook_client.py
already uses for this app's one other machine-to-machine call (chosen there, and here,
because it's simple and needs no header-forwarding guarantees). SCHEDULED_SYNC_SECRET
unset means this route always reports "not configured" and never runs anything — same
fail-closed shape as every other optional integration in this app (see
app/core/config.py's "External integrations — optional" section).

Safe to call as often as a caller likes: each check is idempotent (see
app/services/scheduled_sync.py) and a source that isn't due yet is simply skipped, not
an error.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.services.scheduled_sync import run_due_scheduled_syncs

router = APIRouter(prefix="/api/intelligence", tags=["scheduled-sync"])


class ScheduledSyncCheckRequest(BaseModel):
    secret: str | None = None


class ScheduledSyncCheckResult(BaseModel):
    source: str
    ran: bool
    reason: str


class ScheduledSyncCheckResponse(BaseModel):
    checked_at: datetime
    results: list[ScheduledSyncCheckResult]


def _require_scheduled_sync_secret(payload: ScheduledSyncCheckRequest) -> None:
    configured_secret = get_settings().SCHEDULED_SYNC_SECRET
    if not configured_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Scheduled sync is not configured (SCHEDULED_SYNC_SECRET is not set).",
        )
    if payload.secret != configured_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing secret.")


@router.post("/scheduled-sync-check", response_model=ScheduledSyncCheckResponse)
def scheduled_sync_check(
    payload: ScheduledSyncCheckRequest = ScheduledSyncCheckRequest(), db: Session = Depends(get_db),
):
    _require_scheduled_sync_secret(payload)
    now = datetime.now(timezone.utc)
    results = run_due_scheduled_syncs(db, now)
    return ScheduledSyncCheckResponse(checked_at=now, results=results)
