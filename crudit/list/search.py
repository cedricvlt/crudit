from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select

from crudit.joins import JoinInfo, resolve_nested_column
from crudit.list.filters import as_comparable
from crudit.types import SearchFn


def apply_search(
    query: Select,
    q: str | None,
    model: type[DeclarativeBase],
    join_info: JoinInfo,
    search_fields: list[str],
    search_fn: SearchFn | None,
    current_user: Any,
) -> Select:
    if not q:
        return query

    if search_fn is not None:
        return search_fn(query, q, current_user)

    if not search_fields:
        return query

    conditions = []
    for field_path in search_fields:
        col = as_comparable(resolve_nested_column(field_path, model, join_info))
        conditions.append(col.ilike(f"%{q}%"))

    return query.where(or_(*conditions))
