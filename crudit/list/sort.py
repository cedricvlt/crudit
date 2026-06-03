from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select, nulls_last

from crudit.joins import JoinInfo, resolve_nested_column


def apply_sort(
    query: Select,
    sort_param: str | None,
    model: type[DeclarativeBase],
    join_info: JoinInfo,
    sortable_fields: list[str],
    computed_fields: dict[str, Callable[[type[DeclarativeBase]], Any]] | None = None,
) -> Select:
    if sort_param:
        order_clauses = _parse_sort(
            sort_param, model, join_info, sortable_fields, computed_fields or {}
        )
    else:
        order_clauses = _default_sort(model)

    return query.order_by(*order_clauses)


def _parse_sort(
    sort_param: str,
    model: type[DeclarativeBase],
    join_info: JoinInfo,
    sortable_fields: list[str],
    computed_fields: dict[str, Callable[[type[DeclarativeBase]], Any]],
) -> list[Any]:
    clauses = []
    for part in sort_param.split(","):
        part = part.strip()
        if not part:
            continue
        descending = part.startswith("-")
        field_path = part.lstrip("-")

        if field_path not in sortable_fields:
            raise HTTPException(
                status_code=400,
                detail=f"Field '{field_path}' is not sortable.",
            )

        if field_path in computed_fields:
            col = computed_fields[field_path](model)
        else:
            col = resolve_nested_column(field_path, model, join_info)
        clause = nulls_last(col.desc() if descending else col.asc())
        clauses.append(clause)

    return clauses


def _default_sort(model: type[DeclarativeBase]) -> list[Any]:
    order_fields: tuple[str, ...] = getattr(model, "_order_fields", ())
    clauses = []
    for field_name in order_fields:
        descending = field_name.startswith("-")
        col = getattr(model, field_name.lstrip("-"), None)
        if col is not None:
            clauses.append(nulls_last(col.desc() if descending else col.asc()))
    return clauses
