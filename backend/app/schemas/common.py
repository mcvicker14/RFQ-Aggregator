from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PaginatedResponse(ORMModel):
    items: list
    total: int
    page: int
    page_size: int


class ErrorDetail(BaseModel):
    detail: str
