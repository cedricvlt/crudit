from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select

from crudit.joins import JoinInfo, resolve_filter_path
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
        col, wrappers = resolve_filter_path(field_path, model, join_info)
        predicate = as_comparable(col).ilike(f"%{q}%")
        # Paths traversing a collection (o2m / m2m) carry EXISTS wrappers: wrap
        # the leaf ILIKE innermost-first via `.any()` (collection) / `.has()`
        # (scalar). `wrappers` is empty for plain columns and pure m2o chains,
        # so those keep their existing JOIN-based behavior unchanged.
        for rel_attr, is_collection in reversed(wrappers):
            predicate = rel_attr.any(predicate) if is_collection else rel_attr.has(predicate)
        conditions.append(predicate)

    return query.where(or_(*conditions))
