from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import String, and_, cast, or_
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select
from sqlalchemy.types import TypeDecorator

from crudit.joins import JoinInfo, is_id_column, resolve_filter_path
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
        if isinstance(value, str):
            value = _coerce(col, value)
        query = query.where(col == value)
    return query

_RESERVED_PARAMS = frozenset(
    {"sort", "page", "itemsPerPage", "offset", "limit", "q", "countOnly"}
)

_DATE_PERIOD_OPERATORS = frozenset({"year", "quarter", "month", "week", "relative"})

_RANGE_OPERATORS = frozenset({"lt", "lte", "gt", "gte"})

_OPERATORS = frozenset(
    {"eq", "ne", "lt", "lte", "gt", "gte", "in", "like", "ilike", "isnull"}
) | _DATE_PERIOD_OPERATORS


def apply_filters(
    query: Select,
    raw_params: dict[str, list[str]],
    model: type[DeclarativeBase],
    join_info: JoinInfo,
    filterable_fields: list[str],
    filter_fns: dict[str, FilterFn],
    current_user: Any,
    computed_fields: dict[str, Callable[[type[DeclarativeBase]], Any]] | None = None,
) -> Select:
    computed_fields = computed_fields or {}
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

        if field_path in computed_fields:
            col, wrappers = computed_fields[field_path](model), []
        else:
            col, wrappers = resolve_filter_path(field_path, model, join_info)
        if operator in _RANGE_OPERATORS and is_id_column(col):
            raise HTTPException(
                status_code=400,
                detail=f"Operator '{operator}' is not supported on id field '{field_path}'.",
            )
        if len(raw_values) == 1:
            predicate = _build_expression(col, operator, raw_values[0])
        else:
            predicate = or_(*[_build_expression(col, operator, v) for v in raw_values])
        # For paths traversing a collection, wrap the leaf comparison in
        # EXISTS subqueries (`.any()` for collections, `.has()` for scalars),
        # innermost-first. `wrappers` is empty for plain/m2o columns.
        for rel_attr, is_collection in reversed(wrappers):
            predicate = rel_attr.any(predicate) if is_collection else rel_attr.has(predicate)
        query = query.where(predicate)

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


def _range_year(value: str) -> tuple[date, date]:
    try:
        year = int(value)
    except ValueError:
        raise HTTPException(400, detail=f"Invalid __year value: '{value}'. Expected YYYY.")
    return date(year, 1, 1), date(year + 1, 1, 1)


def _range_quarter(value: str) -> tuple[date, date]:
    try:
        year_str, q_str = value.split("-")
        year = int(year_str)
        q = int(q_str[1:])
        if not (1 <= q <= 4):
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(400, detail=f"Invalid __quarter value: '{value}'. Expected YYYY-Q[1-4].")
    start_month = (q - 1) * 3 + 1
    end_month = start_month + 3
    end_year = year + (1 if end_month > 12 else 0)
    end_month = end_month if end_month <= 12 else end_month - 12
    return date(year, start_month, 1), date(end_year, end_month, 1)


def _range_month(value: str) -> tuple[date, date]:
    try:
        if len(value) != 7 or value[4] != "-":
            raise ValueError
        year, month = int(value[:4]), int(value[5:7])
        if not (1 <= month <= 12):
            raise ValueError
    except (ValueError, IndexError):
        raise HTTPException(400, detail=f"Invalid __month value: '{value}'. Expected YYYY-MM.")
    next_month = month + 1
    next_year = year + (1 if next_month > 12 else 0)
    next_month = next_month if next_month <= 12 else 1
    return date(year, month, 1), date(next_year, next_month, 1)


def _range_week(value: str) -> tuple[date, date]:
    try:
        year_str, w_str = value.split("-")
        year = int(year_str)
        week = int(w_str[1:])
        start = date.fromisocalendar(year, week, 1)
    except (ValueError, AttributeError):
        raise HTTPException(400, detail=f"Invalid __week value: '{value}'. Expected YYYY-Www.")
    return start, start + timedelta(days=7)


_RELATIVE_TERMS = frozenset({
    "today", "yesterday",
    "this-week", "last-week",
    "this-month", "last-month",
    "this-quarter", "last-quarter",
    "this-year", "last-year",
})


def _range_relative(value: str) -> tuple[date, date]:
    if value not in _RELATIVE_TERMS:
        raise HTTPException(
            400,
            detail=f"Invalid __relative value: '{value}'. "
                   f"Supported: {', '.join(sorted(_RELATIVE_TERMS))}.",
        )
    today = date.today()
    if value == "today":
        return today, today + timedelta(days=1)
    if value == "yesterday":
        return today - timedelta(days=1), today
    if value == "this-week":
        monday = today - timedelta(days=today.weekday())
        return monday, monday + timedelta(days=7)
    if value == "last-week":
        monday = today - timedelta(days=today.weekday() + 7)
        return monday, monday + timedelta(days=7)
    if value == "this-month":
        return _range_month(f"{today.year:04d}-{today.month:02d}")
    if value == "last-month":
        first = (date(today.year, today.month, 1) - timedelta(days=1)).replace(day=1)
        return _range_month(f"{first.year:04d}-{first.month:02d}")
    if value == "this-quarter":
        q = (today.month - 1) // 3 + 1
        return _range_quarter(f"{today.year}-Q{q}")
    if value == "last-quarter":
        q = (today.month - 1) // 3 + 1
        prev_q = q - 1 if q > 1 else 4
        prev_year = today.year if q > 1 else today.year - 1
        return _range_quarter(f"{prev_year}-Q{prev_q}")
    if value == "this-year":
        return _range_year(str(today.year))
    return _range_year(str(today.year - 1))


_RANGE_FNS = {
    "year": _range_year,
    "quarter": _range_quarter,
    "month": _range_month,
    "week": _range_week,
    "relative": _range_relative,
}


def _build_date_period_expression(col: Any, operator: str, raw_value: str) -> Any:
    start_date, end_date = _RANGE_FNS[operator](raw_value)
    python_type = _column_python_type(col)
    if python_type is datetime:
        start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
        end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc)
    else:
        start, end = start_date, end_date
    return and_(col >= start, col < end)


def _parse_key(raw_key: str) -> tuple[str, str]:
    """Split 'city.name__ilike' into ('city.name', 'ilike'). Default operator is 'eq'."""
    if "__" in raw_key:
        # Split on the last __ only — field paths use dots, not underscores
        parts = raw_key.rsplit("__", 1)
        if parts[1] in _OPERATORS:
            return parts[0], parts[1]
    return raw_key, "eq"


def _is_datetime_col(col: Any) -> bool:
    return _column_python_type(col) is datetime


def _column_sql_type(col: Any) -> Any:
    """Return the SQL type instance of an ORM column or column-like expression."""
    for accessor in (lambda c: c.property.columns[0].type, lambda c: c.type):
        try:
            return accessor(col)
        except Exception:  # noqa: BLE001
            continue
    return None


def as_comparable(col: Any) -> Any:
    """Cast string-backed `TypeDecorator` columns to plain `String` for comparison.

    Custom types such as sqlalchemy_utils' `PhoneNumberType` are `TypeDecorator`s
    whose `process_bind_param` parses any bound literal (e.g. into a `PhoneNumber`).
    A filter/search string like ``%555%`` is not a valid phone number, so binding it
    through the decorator raises a parse error. Casting the column to `String` makes
    the comparison operate on the stored text and binds the literal as plain text,
    bypassing the decorator. Non-decorator columns are returned unchanged.
    """
    sql_type = _column_sql_type(col)
    if isinstance(sql_type, TypeDecorator):
        try:
            if sql_type.impl_instance.python_type is str:
                return cast(col, String)
        except Exception:  # noqa: BLE001
            pass
    return col


def _column_python_type(col: Any) -> type | None:
    """Return the Python type of a column or column-like expression.

    Handles both ORM mapped columns (via `col.property.columns[0].type`) and
    bare SQL expressions like scalar subqueries (via `col.type`).
    """
    for accessor in (
        lambda c: c.property.columns[0].type.impl_instance.python_type,
        lambda c: c.property.columns[0].type.python_type,
        lambda c: c.type.python_type,
    ):
        try:
            return accessor(col)
        except Exception:  # noqa: BLE001
            continue
    return None


def _is_date_only_string(value: str) -> bool:
    """Return True if value is a bare date (YYYY-MM-DD) with no time component."""
    try:
        date.fromisoformat(value)
        return "T" not in value and " " not in value and len(value) == 10
    except ValueError:
        return False


def _build_expression(col: Any, operator: str, raw_value: str) -> Any:
    if operator in _DATE_PERIOD_OPERATORS:
        return _build_date_period_expression(col, operator, raw_value)
    col = as_comparable(col)
    if operator == "eq":
        return col == _coerce(col, raw_value)
    if operator == "ne":
        return col != _coerce(col, raw_value)
    if operator == "lt":
        return col < _coerce(col, raw_value)
    if operator == "lte":
        # For datetime columns with a date-only string, treat as "before end of that day"
        # so that records at any time on that date are included.
        if _is_datetime_col(col) and _is_date_only_string(raw_value):
            d = date.fromisoformat(raw_value)
            next_day = d + timedelta(days=1)
            coerced = datetime(next_day.year, next_day.month, next_day.day, tzinfo=timezone.utc)
            return col < coerced
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
    python_type = _column_python_type(col)
    if python_type is None:
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
