import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes import (
    agencies,
    alerts,
    auth,
    companies,
    contacts,
    dashboard,
    documents,
    forecast,
    gonogo,
    ingestion,
    opportunities,
    pipeline_stages,
    reference,
    settings as settings_routes,
    tasks,
    users,
    winloss,
)
from app.core.config import get_settings
from app.db.session import engine

logging.basicConfig(level=logging.INFO)
settings = get_settings()

if settings.is_production and settings.JWT_SECRET_KEY == "INSECURE-DEV-ONLY-CHANGE-ME":
    raise RuntimeError(
        "JWT_SECRET_KEY is still the insecure development default while ENV=production. "
        "Set a real JWT_SECRET_KEY (see backend/.env.example) before starting the server — "
        "refusing to start rather than silently issuing forgeable tokens."
    )

app = FastAPI(
    title=settings.APP_NAME,
    description="Principal Opportunity Intelligence — Find Earlier. Pursue Smarter. Win More.",
    version="0.1.0-mvp",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
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
    ingestion.router,
    settings_routes.router,
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
