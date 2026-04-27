from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select

from crudit.joins import resolve_nested_column
from crudit.types import FilterFn


def extract_filter_params(request_query_params: Any) -> dict[str, list[str]]:
    """Collect non-reserved query params, grouping multiple values per key."""
    result: dict[str, list[str]] = {}
    for k, v in request_query_params.multi_items():
        if k not in _RESERVED_PARAMS:
            result.setdefault(k, []).append(v)
    return result


def apply_path_filters(
    query: Select,
    model: type[DeclarativeBase],
    path_filters: dict[str, str],
    path_params: dict[str, Any],
) -> Select:
    for param_name, field_name in path_filters.items():
        value = path_params.get(param_name)
        if value is None:
            raise HTTPException(
                status_code=400, detail=f"Missing path param '{param_name}'."
            )
        col = getattr(model, field_name, None)
        if col is None:
            raise HTTPException(
                status_code=500, detail=f"Model field '{field_name}' not found."
            )
        query = query.where(col == value)
    return query

_RESERVED_PARAMS = frozenset(
    {"sort", "page", "itemsPerPage", "offset", "limit", "q", "countOnly"}
)

_OPERATORS = frozenset(
    {"eq", "ne", "lt", "lte", "gt", "gte", "in", "like", "ilike", "isnull"}
)


def apply_filters(
    query: Select,
    raw_params: dict[str, list[str]],
    model: type[DeclarativeBase],
    joined_models: dict[str, type],
    filterable_fields: list[str],
    filter_fns: dict[str, FilterFn],
    current_user: Any,
) -> Select:
    for raw_key, raw_values in raw_params.items():
        if raw_key in _RESERVED_PARAMS:
            continue

        field_path, operator = _parse_key(raw_key)

        if field_path not in filterable_fields:
            raise HTTPException(
                status_code=400,
                detail=f"Field '{field_path}' is not filterable.",
            )

        if field_path in filter_fns:
            # custom filter_fn receives the first value for backward compatibility
            query = filter_fns[field_path](query, raw_values[0], current_user)
            continue

        col = resolve_nested_column(field_path, model, joined_models)
        if len(raw_values) == 1:
            query = query.where(_build_expression(col, operator, raw_values[0]))
        else:
            query = query.where(or_(*[_build_expression(col, operator, v) for v in raw_values]))

    return query


def apply_default_filters(
    query: Select,
    model: type[DeclarativeBase],
    default_filters: dict[str, Any],
) -> Select:
    for field_name, value in default_filters.items():
        col = getattr(model, field_name, None)
        if col is None:
            raise ValueError(f"Default filter field '{field_name}' not found on {model.__name__}.")
        query = query.where(col == value)
    return query


def _parse_key(raw_key: str) -> tuple[str, str]:
    """Split 'city.name__ilike' into ('city.name', 'ilike'). Default operator is 'eq'."""
    if "__" in raw_key:
        # Split on the last __ only — field paths use dots, not underscores
        parts = raw_key.rsplit("__", 1)
        if parts[1] in _OPERATORS:
            return parts[0], parts[1]
    return raw_key, "eq"


def _build_expression(col: Any, operator: str, raw_value: str) -> Any:
    if operator == "eq":
        return col == _coerce(col, raw_value)
    if operator == "ne":
        return col != _coerce(col, raw_value)
    if operator == "lt":
        return col < _coerce(col, raw_value)
    if operator == "lte":
        return col <= _coerce(col, raw_value)
    if operator == "gt":
        return col > _coerce(col, raw_value)
    if operator == "gte":
        return col >= _coerce(col, raw_value)
    if operator == "in":
        values = [_coerce(col, v.strip()) for v in raw_value.split(",")]
        return col.in_(values)
    if operator == "like":
        return col.like(raw_value)
    if operator == "ilike":
        return col.ilike(raw_value)
    if operator == "isnull":
        is_null = raw_value.lower() in ("true", "1", "yes")
        return col.is_(None) if is_null else col.isnot(None)
    raise ValueError(f"Unknown operator '{operator}'.")


def _coerce(col: Any, value: str) -> Any:
    """Minimal type coercion based on the column's Python type."""
    try:
        python_type = col.property.columns[0].type.impl_instance.python_type
    except Exception:
        try:
            python_type = col.property.columns[0].type.python_type
        except Exception:
            return value

    if python_type is bool:
        return value.lower() in ("true", "1", "yes")
    if python_type is datetime:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return value
    if python_type is date:
        try:
            return date.fromisoformat(value)
        except ValueError:
            return value
    try:
        return python_type(value)
    except (ValueError, TypeError):
        return value
