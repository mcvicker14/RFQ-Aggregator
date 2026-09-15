from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import ORMModel


class NaicsCodeRead(ORMModel):
    id: UUID
    code: str
    title: str
    is_core_market: bool


class DisciplineRead(ORMModel):
    id: UUID
    name: str
    category: str | None = None


class PipelineStageRead(ORMModel):
    id: UUID
    name: str
    sort_order: int
    is_closed_won: bool
    is_closed_lost: bool
    is_active: bool


class PipelineStageUpdate(BaseModel):
    id: UUID
    name: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
