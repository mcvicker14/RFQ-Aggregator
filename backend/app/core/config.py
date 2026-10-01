"""Application configuration, read entirely from environment variables.

Nothing in this file should ever contain a real secret. Local development values
live in `backend/.env` (gitignored); `backend/.env.example` documents every variable
with a placeholder. See docs/SECURITY.md.
"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENV: str = "development"
    APP_NAME: str = "Principal Opportunity Intelligence"

    DATABASE_URL: str = (
        "postgresql+psycopg://principal_oi_app:dev_local_only_pw_change_me"
        "@localhost:5432/principal_oi"
    )

    @field_validator("DATABASE_URL")
    @classmethod
    def _use_psycopg3_driver(cls, value: str) -> str:
        """Managed Postgres providers (Render, Railway, etc.) hand out a bare
        postgres:// or postgresql:// connection string. SQLAlchemy needs the
        +psycopg driver suffix to use psycopg3 (what's actually installed — see
        requirements.txt). Normalizing here means a hosting provider's connection
        string can be pasted in as-is, with no manual editing required."""
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://"):]
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://"):]
        return value

    # JWT auth
    JWT_SECRET_KEY: str = "INSECURE-DEV-ONLY-CHANGE-ME"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12

    # CORS
    FRONTEND_ORIGIN: str = "http://localhost:3000"

    # File storage (local disk by default; see app/services/storage.py)
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 25

    # Principal Engineering firm profile. 541330 (Engineering Services) is Principal's
    # primary NAICS code and gets the strongest weighting everywhere NAICS relevance is
    # scored — discovery filters, the Principal Pursuit Score's Strategic/Contract Fit
    # categories, and SAM.gov sync defaults. See docs/SCORING_METHODOLOGY.md.
    PRINCIPAL_PRIMARY_NAICS: str = "541330"
    # Secondary/related codes Principal also pursues; still scored favorably but below
    # the primary code. Editable here without touching scoring logic.
    PRINCIPAL_SECONDARY_NAICS: list[str] = [
        "541620",  # Environmental Consulting Services
        "541370",  # Surveying and Mapping (except Geophysical) Services
        "541380",  # Testing Laboratories
        "541320",  # Landscape Architectural Services
        "237990",  # Other Heavy and Civil Engineering Construction
        "541690",  # Other Scientific and Technical Consulting Services
    ]

    # External integrations — optional. Each feature that depends on one of these
    # degrades to a clear "not configured" state rather than failing silently or
    # faking a result. See docs/DATA_INGESTION.md and docs/SECURITY.md.
    SAM_GOV_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-sonnet-5"

    # COREWORKS RFQwire connector — this app holds no Gmail/Google credentials of any
    # kind. A Google Apps Script, authorized directly against the Gmail account that
    # receives forwarded COREWORKS digest emails (not this app), does the actual
    # searching and reads; it POSTs matching message content to this app's
    # coreworks-ingest webhook and answers this app's own on-demand "Sync Now" calls,
    # authenticated both ways by this shared secret in the request body (same pattern
    # as STATUS_BOARD_WEBHOOK_SECRET below). See app/connectors/
    # coreworks_apps_script_client.py and google-apps-script/coreworks_sync.gs.
    COREWORKS_APPS_SCRIPT_URL: str | None = None
    COREWORKS_WEBHOOK_SECRET: str | None = None

    # Scheduled-sync trigger (COREWORKS polling / APEX daily 6PM Central) — a shared
    # secret for an external scheduler (e.g. a GitHub Actions cron workflow) to call
    # the scheduled-sync-check endpoint, same shared-secret-in-body pattern as
    # STATUS_BOARD_WEBHOOK_SECRET above, since this app has no other machine-to-machine
    # auth mechanism. See app/api/routes/scheduled_sync.py.
    SCHEDULED_SYNC_SECRET: str | None = None

    # SOQ Status Board sync — see app/services/status_board_sync.py and
    # app/services/status_board_webhook_client.py. This app holds no Google
    # credentials at all; it POSTs to a Google Apps Script Web App (bound to the SOQ
    # Status Board sheet) that does the actual read/write, authenticated by a shared
    # secret this app sends in the request body. Neither value is a real value in
    # source control; set both only via Render's environment variables. See
    # google-apps-script/status_board_sync.gs for the script these point at.
    STATUS_BOARD_WEBHOOK_URL: str | None = None
    STATUS_BOARD_WEBHOOK_SECRET: str | None = None
    # Purely cosmetic: the actual spreadsheet's own URL (docs.google.com/spreadsheets/
    # d/...), used only to render an "Open in Google Sheets" link on the Status Board
    # page. Optional and separate from STATUS_BOARD_WEBHOOK_URL (the Apps Script's own
    # /exec URL, which isn't something a person would ever want to open directly) —
    # the link is simply omitted if this isn't set.
    STATUS_BOARD_SHEET_URL: str | None = None

    # Object storage (Phase 2 — local disk is the default StorageBackend today)
    STORAGE_BACKEND: str = "local"  # "local" | "s3" | "azure_blob"
    S3_BUCKET: str | None = None
    AZURE_STORAGE_CONNECTION_STRING: str | None = None
    AZURE_STORAGE_CONTAINER: str | None = None

    # Outbound email (Phase 1 — alert data model exists; no provider wired yet)
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    ALERTS_FROM_EMAIL: str | None = None

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
