from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    data: list[T]
    total_count: int
    has_more: bool
    page: int
    items_per_page: int


class CountOnlyResponse(BaseModel):
    total_count: int
