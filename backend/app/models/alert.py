import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid, pg_enum
from app.models.enums import AlertCategory


class Alert(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "alerts"

    user_id: Mapped[uuid.UUID | None] = fk_uuid(
        "users.id", nullable=True
    )  # null = firm-wide alert, visible to all users
    category: Mapped[AlertCategory] = mapped_column(pg_enum(AlertCategory), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, default=None)
    opportunity_id: Mapped[uuid.UUID | None] = fk_uuid("opportunities.id", nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    email_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )  # null until an email provider is configured, see docs/ROADMAP.md Phase 1


class AlertRule(UUIDPKMixin, TimestampMixin, Base):
    """Per-user alert configuration, spec §15."""

    __tablename__ = "alert_rules"

    user_id: Mapped[uuid.UUID] = fk_uuid("users.id")
    category: Mapped[AlertCategory] = mapped_column(pg_enum(AlertCategory), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    filters: Mapped[dict | None] = mapped_column(
        JSONB, default=None
    )  # e.g. {"states": ["LA"], "set_aside": "sdvosb"}
    deliver_in_app: Mapped[bool] = mapped_column(Boolean, default=True)
    deliver_email: Mapped[bool] = mapped_column(Boolean, default=False)
