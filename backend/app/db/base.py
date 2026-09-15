import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPKMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


def fk_uuid(target: str, nullable: bool = False, ondelete: str = "CASCADE"):
    """Shorthand for a UUID foreign-key column, e.g. fk_uuid("opportunities.id")."""
    from sqlalchemy import ForeignKey

    return mapped_column(UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable)


def pg_enum(enum_cls: type[enum.Enum]) -> SAEnum:
    """Store Python enums as VARCHAR + CHECK constraint (native_enum=False) rather than
    a native Postgres ENUM type, so adding a new value later is a normal migration
    instead of an ALTER TYPE dance."""
    return SAEnum(enum_cls, native_enum=False, values_callable=lambda x: [e.value for e in x])


class ProvenanceMixin:
    """Every externally-sourced or AI-derived record carries these. See docs/SECURITY.md
    and docs/DATABASE_SCHEMA.md §Provenance. Manually entered data is stored with
    source="Manual Entry" and confidence="verified_fact" — the human is the source."""

    source: Mapped[str] = mapped_column(default="Manual Entry", nullable=False)
    source_url: Mapped[str | None] = mapped_column(default=None)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    confidence: Mapped[str] = mapped_column(default="verified_fact", nullable=False)
