import uuid
from datetime import date

from sqlalchemy import Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid


class RevenueForecast(UUIDPKMixin, TimestampMixin, Base):
    """One row per opportunity, spec §19. Weighted value is computed server-side
    (estimated_fee * probability) rather than stored redundantly-writable, to avoid
    drift — see services/forecasting.py."""

    __tablename__ = "revenue_forecasts"

    opportunity_id: Mapped[uuid.UUID] = fk_uuid("opportunities.id", nullable=False)

    total_contract_value: Mapped[float | None] = mapped_column(Numeric(14, 2), default=None)
    principal_share_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), default=None)  # 0-100
    estimated_fee: Mapped[float | None] = mapped_column(Numeric(14, 2), default=None)
    win_probability_pct: Mapped[float | None] = mapped_column(Numeric(5, 2), default=None)  # 0-100
    expected_award_date: Mapped[date | None] = mapped_column(Date, default=None)
    expected_revenue_start: Mapped[date | None] = mapped_column(Date, default=None)
    expected_revenue_end: Mapped[date | None] = mapped_column(Date, default=None)
    market_sector: Mapped[str | None] = mapped_column(String(120), default=None)


class RevenueTarget(UUIDPKMixin, TimestampMixin, Base):
    """Admin-settable target revenue per period, used for the Revenue Gap KPI."""

    __tablename__ = "revenue_targets"

    period_label: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)  # e.g. "2026", "2026-Q3"
    target_amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
