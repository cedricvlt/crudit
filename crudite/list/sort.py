from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select, nulls_last

from crudite.joins import resolve_nested_column


def apply_sort(
    query: Select,
    sort_param: str | None,
    model: type[DeclarativeBase],
    joined_models: dict[str, type],
    sortable_fields: list[str],
) -> Select:
    if sort_param:
        order_clauses = _parse_sort(sort_param, model, joined_models, sortable_fields)
    else:
        order_clauses = _default_sort(model)

    return query.order_by(*order_clauses)


def _parse_sort(
    sort_param: str,
    model: type[DeclarativeBase],
    joined_models: dict[str, type],
    sortable_fields: list[str],
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

        col = resolve_nested_column(field_path, model, joined_models)
        clause = nulls_last(col.desc() if descending else col.asc())
        clauses.append(clause)

    return clauses


def _default_sort(model: type[DeclarativeBase]) -> list[Any]:
    order_fields: tuple[str, ...] = getattr(model, "_order_fields", ())
    clauses = []
    for field_name in order_fields:
        col = getattr(model, field_name, None)
        if col is not None:
            clauses.append(nulls_last(col.asc()))
    return clauses
