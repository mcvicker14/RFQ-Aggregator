"""Four daily Central-time board snapshots, independent of intake scheduling.

The separate board-only external check wakes Free Render, reusing the existing
scheduler credential. An in-process check is a fallback, not a clock guarantee.
Delayed checks reconcile the latest
due slot once; missed slots never replay old decisions or restore deleted rows.
"""
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.status_board_read_sync import refresh_status_board_cache

logger = logging.getLogger(__name__)
CENTRAL_TZ = ZoneInfo("America/Chicago")
RECONCILIATION_HOURS = (9, 12, 16, 20)


def latest_due_slot(now: datetime) -> datetime:
    if now.tzinfo is None:
        raise ValueError("An aware timestamp is required.")
    local = now.astimezone(CENTRAL_TZ)
    due = [hour for hour in RECONCILIATION_HOURS if hour <= local.hour]
    day = local.date() if due else local.date() - timedelta(days=1)
    hour = due[-1] if due else RECONCILIATION_HOURS[-1]
    return datetime.combine(day, time(hour), CENTRAL_TZ).astimezone(timezone.utc)


def run_due_board_reconciliation(db: Session, now: datetime | None = None) -> dict:
    if not get_settings().STATUS_BOARD_RECONCILIATION_ENABLED:
        return {"reason": "disabled", "slot_at": None, "last_error": None}
    now = now or datetime.now(timezone.utc)
    slot = latest_due_slot(now)
    state = refresh_status_board_cache(db, scheduled_slot=slot, now=now)
    complete = bool(state.last_reconciliation_slot_at and state.last_reconciliation_slot_at >= slot)
    attempted = state.last_reconciliation_attempted_at == now
    reason = "completed" if complete else "failed" if attempted else "busy_or_retry_wait"
    error = state.last_reconciliation_error if not complete else None
    logger.log(logging.WARNING if reason == "failed" else logging.INFO,
               "Status Board reconciliation slot=%s reason=%s rows=%s", slot.isoformat(), reason, state.row_count)
    return {"reason": reason, "slot_at": slot, "last_error": error}
