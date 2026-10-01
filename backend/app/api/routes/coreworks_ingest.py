"""COREWORKS RFQwire ingest webhook — the push half of the Apps Script integration (see
app/connectors/gmail_coreworks.py and google-apps-script/coreworks_sync.gs). The Apps
Script's own time-driven trigger (every 3 hours) calls this directly, without the
backend asking first, whenever it finds new confirmed COREWORKS messages; "Sync Now"
and the generic scheduled-sync pull instead go through
CoreworksRfqwireConnector.fetch() -> run_sync() as normal, never through this route.

Deliberately NOT user-JWT-authenticated (Depends(get_current_user)/require_*) — this is
called by an unattended Apps Script trigger, not a logged-in person. Auth is a shared
secret in the request body, the exact same pattern app/api/routes/scheduled_sync.py and
app/services/status_board_webhook_client.py already use for this app's other two
machine-to-machine calls.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.gmail_coreworks import SOURCE_NAME, parse_messages_to_raw_items
from app.core.config import get_settings
from app.db.session import get_db
from app.models.intelligence import IntelligenceSource
from app.services.intelligence_sync import SyncAlreadyRunningError, ingest_pushed_items

router = APIRouter(prefix="/api/intelligence", tags=["coreworks-ingest"])


class CoreworksMessage(BaseModel):
    id: str
    body_text: str
    internal_date_ms: int | str | None = None


class CoreworksIngestRequest(BaseModel):
    secret: str | None = None
    messages: list[CoreworksMessage] = []


class CoreworksIngestResponse(BaseModel):
    ok: bool
    sync_run_id: str
    items_fetched: int
    items_created: int
    items_updated: int
    items_deduplicated: int
    items_errored: int


@router.post("/coreworks-ingest", response_model=CoreworksIngestResponse)
def coreworks_ingest(payload: CoreworksIngestRequest, db: Session = Depends(get_db)):
    configured_secret = get_settings().COREWORKS_WEBHOOK_SECRET
    if not configured_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "COREWORKS ingest is not configured (COREWORKS_WEBHOOK_SECRET is not set).",
        )
    if payload.secret != configured_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing secret.")

    source = db.execute(
        select(IntelligenceSource).where(IntelligenceSource.name == SOURCE_NAME)
    ).scalars().first()
    if source is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"'{SOURCE_NAME}' intelligence source is not seeded — nothing to ingest into.",
        )

    raw_items = parse_messages_to_raw_items([m.model_dump() for m in payload.messages])
    try:
        run = ingest_pushed_items(db, source, raw_items)
    except SyncAlreadyRunningError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    return CoreworksIngestResponse(
        ok=run.status.value != "failure",
        sync_run_id=str(run.id),
        items_fetched=run.items_fetched or 0,
        items_created=run.items_created or 0,
        items_updated=run.items_updated or 0,
        items_deduplicated=run.items_deduplicated or 0,
        items_errored=run.items_errored or 0,
    )
