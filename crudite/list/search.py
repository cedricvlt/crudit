from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select

from crudite.joins import resolve_nested_column
from crudite.types import SearchFn


def apply_search(
    query: Select,
    q: str | None,
    model: type[DeclarativeBase],
    joined_models: dict[str, type],
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
        col = resolve_nested_column(field_path, model, joined_models)
        conditions.append(col.ilike(f"%{q}%"))

    return query.where(or_(*conditions))
