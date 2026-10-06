"""Durable human-requested cell edits, independent of replaceable board cache."""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, TimestampMixin, UUIDPKMixin, fk_uuid


class StatusBoardEdit(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "status_board_edits"
    request_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    actor_id = fk_uuid("users.id", nullable=True, ondelete="SET NULL")
    source_record_id: Mapped[str] = mapped_column(String(36), nullable=False)
    expected_revision: Mapped[str] = mapped_column(String(64), nullable=False)
    old_value: Mapped[str] = mapped_column(String(10), nullable=False)
    new_value: Mapped[str] = mapped_column(String(1), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    result_revision: Mapped[str | None] = mapped_column(String(64), default=None)
