from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.sql import Select


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


@dataclass
class PaginationResult:
    sql_offset: int
    sql_limit: int
    page: int
    items_per_page: int


def resolve_pagination(
    page: int | None,
    items_per_page: int | None,
    offset: int | None,
    limit: int | None,
) -> PaginationResult:
    # Offset mode takes priority if either offset or limit is present
    if offset is not None or limit is not None:
        sql_offset = offset or 0
        sql_limit = limit or 25
        page_num = sql_offset // sql_limit + 1
        return PaginationResult(
            sql_offset=sql_offset,
            sql_limit=sql_limit,
            page=page_num,
            items_per_page=sql_limit,
        )

    # Page mode
    page_num = page or 1
    per_page = items_per_page or 25
    sql_offset = (page_num - 1) * per_page
    return PaginationResult(
        sql_offset=sql_offset,
        sql_limit=per_page,
        page=page_num,
        items_per_page=per_page,
    )


def apply_pagination(query: Select, pagination: PaginationResult) -> Select:
    return query.offset(pagination.sql_offset).limit(pagination.sql_limit)
