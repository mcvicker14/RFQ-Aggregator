"""Scheduling for the two sources that need it (COREWORKS RFQwire, APEX MyBidMatch) —
the only two connectors in this app with any scheduling requirement at all. No
scheduling infrastructure existed anywhere in this app before this (confirmed
repo-wide: no APScheduler/celery/cron, no FastAPI startup hook, IntelligenceSource.
polling_frequency_hours and SyncTriggeredBy.SCHEDULED both existed only as
forward-compatible placeholders nothing ever read/used) — this module, the
scheduled-sync-check route that calls it, the in-process APScheduler job in
app/main.py, and the GitHub Actions workflow that calls the route externally are all
new, minimal, and scoped to exactly these two sources. See docs/DATA_INGESTION.md and
this module's own functions for why three layers exist.

Every check here is a pure function of (current time, a source's own last_attempted_
sync_at, its own config) — no wall-clock timer owns "is it time yet" on its own, so the
same due/not-due decision is made identically whether it's asked by the in-process
APScheduler tick, an external GitHub Actions ping, or a test calling the function
directly with a fixed `now`.

APEX's 6:00 PM America/Chicago requirement is DST-correct BY CONSTRUCTION: zoneinfo
(stdlib, no dependency) resolves America/Chicago's actual UTC offset for whatever date
`now` falls on, the same way app/services/status_board_sync.py's CENTRAL_TZ already
does elsewhere in this codebase — there is no fixed-UTC-offset cron expression anywhere
that could be right for only half the year.
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import SyncTriggeredBy
from app.models.intelligence import IntelligenceSource
from app.services.intelligence_sync import SyncAlreadyRunningError, run_sync

logger = logging.getLogger(__name__)

CENTRAL_TZ = ZoneInfo("America/Chicago")  # matches status_board_sync.py's own constant
APEX_SYNC_HOUR_LOCAL = 18  # 6:00 PM America/Chicago, any DST regime

SCHEDULED_SOURCE_NAMES = ("COREWORKS RFQwire", "APEX MyBidMatch")


def should_run_apex_sync_now(now_utc: datetime, last_attempted_sync_at: datetime | None) -> bool:
    """True from the first check at/after 6:00 PM America/Chicago on a given local
    calendar day, through the rest of that same local day, then false again until the
    next day's 6:00 PM — i.e. "due, and not yet run today." Safe to call as often as a
    caller likes (every 15 minutes from the in-process scheduler, every few minutes
    from an external ping) — it only returns True once per local day regardless of how
    many times it's asked, because the second half of the check compares against
    last_attempted_sync_at, which the caller is expected to update via run_sync()
    before the next check runs."""
    local_now = now_utc.astimezone(CENTRAL_TZ)
    if local_now.hour < APEX_SYNC_HOUR_LOCAL:
        return False
    if last_attempted_sync_at is None:
        return True
    last_local = last_attempted_sync_at.astimezone(CENTRAL_TZ)
    return last_local.date() < local_now.date()


def should_run_polling_sync_now(
    now_utc: datetime, last_attempted_sync_at: datetime | None, polling_frequency_hours: int | None,
) -> bool:
    """COREWORKS's gate — a rolling interval, not a fixed clock time, since COREWORKS
    itself mails on no fixed schedule (real examples show "(Midday)"/"(AM)" sent at
    different times). Reuses IntelligenceSource.polling_frequency_hours, a column that
    already existed on the model but was never read by any code before this."""
    if not polling_frequency_hours or polling_frequency_hours <= 0:
        return False
    if last_attempted_sync_at is None:
        return True
    return now_utc - last_attempted_sync_at >= timedelta(hours=polling_frequency_hours)


def run_due_scheduled_syncs(db: Session, now: datetime | None = None) -> list[dict]:
    """The one place that decides, for COREWORKS and APEX specifically, whether each
    is due and runs it if so — shared by the external-facing route
    (app/api/routes/scheduled_sync.py, which wraps this with shared-secret auth for an
    outside caller) and the in-process APScheduler safety net (app/main.py, which is
    already inside the trusted server process and calls this directly). Kept in one
    place so "is it due" can never drift between the two call paths."""
    now = now or datetime.now(timezone.utc)
    sources = db.execute(
        select(IntelligenceSource).where(IntelligenceSource.name.in_(SCHEDULED_SOURCE_NAMES))
    ).scalars().all()

    results = []
    for source in sources:
        if not source.is_enabled or source.connector_key is None:
            results.append({"source": source.name, "ran": False, "reason": "disabled or no connector"})
            continue

        if source.name == "APEX MyBidMatch":
            due = should_run_apex_sync_now(now, source.last_attempted_sync_at)
            reason = "due (>= 6:00 PM America/Chicago, not yet run today)" if due else "not due yet today"
        else:
            due = should_run_polling_sync_now(now, source.last_attempted_sync_at, source.polling_frequency_hours)
            reason = f"due (polling interval {source.polling_frequency_hours}h elapsed)" if due else "polling interval not elapsed"

        if not due:
            results.append({"source": source.name, "ran": False, "reason": reason})
            continue

        try:
            run_sync(db, source, SyncTriggeredBy.SCHEDULED)
            results.append({"source": source.name, "ran": True, "reason": reason})
        except SyncAlreadyRunningError as exc:
            results.append({"source": source.name, "ran": False, "reason": str(exc)})
        except ValueError as exc:
            results.append({"source": source.name, "ran": False, "reason": str(exc)})
        except Exception:
            logger.exception("run_due_scheduled_syncs: run_sync raised unexpectedly for '%s'", source.name)
            results.append({"source": source.name, "ran": False, "reason": "unexpected error — see logs"})

    return results
