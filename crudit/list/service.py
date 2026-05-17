from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from crudit.context import CruditContext
from crudit.joins import JoinInfo, collect_needed_joins, resolve_joins
from crudit.list.config import ListConfig
from crudit.list.filters import (
    apply_default_filters,
    apply_filters,
    apply_path_filters,
)
from crudit.list.pagination import apply_pagination, resolve_pagination
from crudit.list.search import apply_search
from crudit.list.sort import apply_sort
from crudit.permissions import apply_permissions
from crudit.schemas import PaginatedResponse
from crudit.utils import call_hook


async def list_service(
    db: AsyncSession,
    ctx: CruditContext,
    *,
    model: type[DeclarativeBase],
    schema: type[BaseModel],
    config: ListConfig,
    path_filters: dict[str, str] | None = None,
    q: str | None = None,
    sort: str | None = None,
    page: int | None = None,
    items_per_page: int | None = None,
    offset: int | None = None,
    limit: int | None = None,
    count_only: bool = False,
    filter_params: dict[str, list[str]] | None = None,
    join_info: JoinInfo | None = None,
) -> PaginatedResponse | int:
    """Run the list business logic and return a `PaginatedResponse` (or the
    total count when ``count_only`` is True).

    This is the entry point for non-HTTP callers (MCP tools, jobs, CLIs).
    `filter_params` is the same shape produced by
    `crudit.list.filters.extract_filter_params`: a mapping of field path to a
    list of raw string values (one entry per ``__suffix``-stripped key).

    `join_info` is optional — it will be resolved from `model`/`schema` if not
    provided. The endpoint layer passes a cached one to avoid re-introspection
    per request.
    """
    if join_info is None:
        join_info = resolve_joins(model, schema)
    if filter_params is None:
        filter_params = {}

    query = select(model)
    query = apply_path_filters(query, model, path_filters or {}, ctx.path_params)
    query = apply_default_filters(query, model, config.default_filters)
    query = apply_permissions(query, model, ctx.user, config.login_required)

    explicitly_joined: set[str] = collect_needed_joins(
        filter_params, sort, join_info, config.search_fields
    )
    query = join_info.apply_explicit_joins(query, model, explicitly_joined)

    query = apply_search(
        query,
        q,
        model,
        join_info,
        config.search_fields,
        config.search_fn,
        ctx.user,
    )

    query = apply_filters(
        query,
        filter_params,
        model,
        join_info,
        config.filterable_fields,
        config.filter_fns,
        ctx.user,
    )

    if config.before_query is not None:
        query = await call_hook(config.before_query, query, ctx)

    computed_names = list(config.computed_fields.keys())
    if computed_names:
        query = query.add_columns(
            *[fn(model).label(name) for name, fn in config.computed_fields.items()]
        )

    # COUNT (before sort/pagination)
    count_query = select(func.count()).select_from(query.subquery())
    total_count = (await db.execute(count_query)).scalar_one()

    if count_only:
        return total_count

    query = apply_sort(
        query,
        sort,
        model,
        join_info,
        config.sortable_fields,
        config.computed_fields,
    )

    pagination = resolve_pagination(page, items_per_page, offset, limit)
    query = apply_pagination(query, pagination)

    options = join_info.eager_load_options(model, explicitly_joined)
    if options:
        query = query.options(*options)

    result = await db.execute(query)
    if computed_names:
        raw = result.unique().all()
        rows = []
        for row in raw:
            instance = row[0]
            for i, name in enumerate(computed_names, start=1):
                setattr(instance, name, row[i])
            rows.append(instance)
    else:
        rows = list(result.scalars().unique())

    join_info.sort_o2m_collections(rows)

    if config.after_query is not None:
        rows = await call_hook(config.after_query, rows, ctx)

    data = [schema.model_validate(row, from_attributes=True) for row in rows]

    return PaginatedResponse(
        data=data,
        total_count=total_count,
        has_more=(pagination.sql_offset + pagination.sql_limit) < total_count,
        page=pagination.page,
        items_per_page=pagination.items_per_page,
    )


def _list_response_model(schema: type[BaseModel]) -> Any:
    """Helper for endpoints that wraps the schema in PaginatedResponse[schema]."""
    return PaginatedResponse[schema]
