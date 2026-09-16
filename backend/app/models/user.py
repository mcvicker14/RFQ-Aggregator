from datetime import datetime

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin, pg_enum
from app.models.enums import UserRole


class User(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(pg_enum(UserRole), nullable=False, default=UserRole.VIEWER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), default=None)
    # Read, not written, by build_dashboard_summary — it reports "new intelligence"
    # against whatever this held *before* the current dashboard load, then advances it
    # to now (see docs/PHASE2_ARCHITECTURE.md §11). NULL means "never viewed yet."
    intelligence_last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
