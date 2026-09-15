"""Application configuration, read entirely from environment variables.

Nothing in this file should ever contain a real secret. Local development values
live in `backend/.env` (gitignored); `backend/.env.example` documents every variable
with a placeholder. See docs/SECURITY.md.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ENV: str = "development"
    APP_NAME: str = "Principal Opportunity Intelligence"

    DATABASE_URL: str = (
        "postgresql+psycopg://principal_oi_app:dev_local_only_pw_change_me"
        "@localhost:5432/principal_oi"
    )

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
