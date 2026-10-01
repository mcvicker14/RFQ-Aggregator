import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import (
    agencies,
    alerts,
    auth,
    companies,
    contacts,
    coreworks_ingest,
    dashboard,
    documents,
    forecast,
    gonogo,
    intelligence_items,
    intelligence_sources,
    opportunities,
    pipeline_stages,
    reference,
    sample_data_audit,
    sample_data_cleanup,
    scheduled_sync,
    settings as settings_routes,
    status_board,
    tasks,
    users,
    winloss,
)
from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.services import status_board_webhook_client
from app.services.scheduled_sync import run_due_scheduled_syncs
from app.services.status_board_read_sync import refresh_status_board_cache

logging.basicConfig(level=logging.INFO)
settings = get_settings()

if settings.is_production and settings.JWT_SECRET_KEY == "INSECURE-DEV-ONLY-CHANGE-ME":
    raise RuntimeError(
        "JWT_SECRET_KEY is still the insecure development default while ENV=production. "
        "Set a real JWT_SECRET_KEY (see backend/.env.example) before starting the server — "
        "refusing to start rather than silently issuing forgeable tokens."
    )

logger = logging.getLogger(__name__)


def _run_scheduled_sync_tick() -> None:
    """In-process safety net for COREWORKS/APEX scheduling — see
    app/services/scheduled_sync.py's module docstring for the full three-layer design
    and why an in-process-only scheduler isn't sufficient on its own (this web
    process, like any free-tier Render web service, can sleep when idle; an external
    GitHub Actions ping is what guarantees the check still happens even then). Runs
    every SCHEDULED_SYNC_TICK_MINUTES while this process is awake, does nothing if
    SCHEDULED_SYNC_SECRET isn't set (that only gates the EXTERNAL route, not this
    in-process call, which needs no secret since it's already inside the trusted
    process) — this tick always attempts the check; run_due_scheduled_syncs() itself
    is what decides nothing is actually due most of the time."""
    db = SessionLocal()
    try:
        results = run_due_scheduled_syncs(db)
        ran = [r for r in results if r["ran"]]
        if ran:
            logger.info("Scheduled sync tick ran: %s", ran)
    except Exception:
        logger.exception("Scheduled sync tick failed")
    finally:
        db.close()


def _run_status_board_cache_tick() -> None:
    """In-process automatic Status Board refresh — every STATUS_BOARD_CACHE_TICK_
    MINUTES while this process is awake, same "attempt always, no-op if not
    configured" shape as _run_scheduled_sync_tick above. No external-scheduler layer
    for this one (unlike COREWORKS/APEX): a stale cache for the few extra minutes
    until this process next wakes from idle is low-stakes (the manual Refresh button
    always catches it up immediately), unlike missing a COREWORKS listing entirely —
    see app/services/scheduled_sync.py's module docstring for why that one DOES need
    the extra layer. Does nothing if STATUS_BOARD_WEBHOOK_URL/SECRET aren't set."""
    if not status_board_webhook_client.is_configured():
        return
    db = SessionLocal()
    try:
        state = refresh_status_board_cache(db)
        if state.last_error:
            logger.warning("Status Board cache tick failed: %s", state.last_error)
    except Exception:
        logger.exception("Status Board cache tick failed")
    finally:
        db.close()


SCHEDULED_SYNC_TICK_MINUTES = 15
STATUS_BOARD_CACHE_TICK_MINUTES = 10
_scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _scheduler.add_job(
        _run_scheduled_sync_tick, "interval", minutes=SCHEDULED_SYNC_TICK_MINUTES, id="scheduled_sync_tick",
    )
    _scheduler.add_job(
        _run_status_board_cache_tick, "interval", minutes=STATUS_BOARD_CACHE_TICK_MINUTES, id="status_board_cache_tick",
    )
    _scheduler.start()
    yield
    _scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.APP_NAME,
    description="Principal Opportunity Intelligence — Find Earlier. Pursue Smarter. Win More.",
    version="0.1.0-mvp",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    auth.router,
    users.router,
    dashboard.router,
    opportunities.router,
    gonogo.router,
    tasks.router,
    documents.router,
    forecast.router,
    agencies.router,
    companies.router,
    contacts.router,
    pipeline_stages.router,
    reference.router,
    alerts.router,
    intelligence_items.router,
    intelligence_sources.router,
    coreworks_ingest.router,
    sample_data_audit.router,
    sample_data_cleanup.router,
    scheduled_sync.router,
    settings_routes.router,
    status_board.router,
    winloss.router,
):
    app.include_router(router)


@app.get("/api/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": db_ok, "app": settings.APP_NAME}
