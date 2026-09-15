from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPKMixin

# Default stage set, spec §18. Seeded once; administrators may rename/reorder/add
# via PATCH /api/pipeline-stages (see docs/API_STRUCTURE.md).
DEFAULT_STAGES = [
    "Signal Detected",
    "Researching",
    "Capture",
    "Go/No-Go",
    "Teaming",
    "Solicitation Released",
    "Proposal Development",
    "Submitted",
    "Shortlisted",
    "Interview",
    "Negotiation",
    "Award Pending",
    "Won",
    "Lost",
    "No Bid",
]


class PipelineStage(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "pipeline_stages"

    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    sort_order: Mapped[int] = mapped_column(nullable=False)
    is_closed_won: Mapped[bool] = mapped_column(Boolean, default=False)
    is_closed_lost: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
