from __future__ import annotations

from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from crudit.joins import collect_needed_joins, resolve_joins
from crudit.list.config import ListConfig
from crudit.types import PermissionDepFn
from crudit.list.filters import (
    apply_default_filters,
    apply_filters,
    apply_path_filters,
    extract_filter_params,
)
from crudit.list.pagination import apply_pagination, resolve_pagination
from crudit.list.search import apply_search
from crudit.list.sort import apply_sort
from crudit.permissions import apply_permissions
from crudit.schemas import PaginatedResponse
from crudit.signature import inject_query_params
from crudit.utils import bind_perms, call_hook, get_error_responses, user_dep_or_none


def list_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    schema: type[BaseModel],
    config: ListConfig,
    *,
    login_dep: Callable | None = None,
    permission_dep: PermissionDepFn | None = None,
    summary: str | None = None,
    get_db: Callable,
) -> None:
    """
    Register a paginated list GET endpoint on `router`.

    Join resolution and config validation happen here (once), not per-request.
    """
    join_info = resolve_joins(model, schema)

    _model = model
    _schema = schema
    _config = config
    _join_info = join_info

    db_dep = Depends(get_db)
    user_dep = user_dep_or_none(login_dep)

    async def _handler(
        request: Request,
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
        q: str | None = None,
        sort: str | None = None,
        page: int | None = None,
        items_per_page: Annotated[int | None, Query(alias="itemsPerPage")] = None,
        offset: int | None = None,
        limit: int | None = None,
        count_only: Annotated[bool, Query(alias="countOnly")] = False,
        **_filter_kwargs,  # absorbs filterable-field params injected via __signature__
    ) -> Any:
        filter_params = extract_filter_params(request.query_params)
        path_params = dict(request.path_params)

        query = select(_model)
        query = apply_path_filters(query, _model, _config.path_filters, path_params)
        query = apply_default_filters(query, _model, _config.default_filters)
        query = apply_permissions(
            query,
            _model,
            current_user,
            _config.login_required,
        )
        explicitly_joined: set[str] = collect_needed_joins(
            filter_params, sort, _join_info, _config.search_fields
        )
        for rel_name in explicitly_joined:
            rel_attr = getattr(_model, rel_name)
            query = query.join(rel_attr, isouter=True)

        query = apply_search(
            query,
            q,
            _model,
            _join_info.joined_models,
            _config.search_fields,
            _config.search_fn,
            current_user,
        )

        query = apply_filters(
            query,
            filter_params,
            _model,
            _join_info.joined_models,
            _config.filterable_fields,
            _config.filter_fns,
            current_user,
        )

        if _config.before_query is not None:
            query = await call_hook(_config.before_query, query, request, current_user)

        # COUNT (before sort/pagination)
        count_query = select(func.count()).select_from(query.subquery())
        total_count = (await db.execute(count_query)).scalar_one()

        if count_only:
            return JSONResponse({"totalCount": total_count})

        query = apply_sort(
            query,
            sort,
            _model,
            _join_info.joined_models,
            _config.sortable_fields,
        )

        pagination = resolve_pagination(page, items_per_page, offset, limit)
        query = apply_pagination(query, pagination)

        # Eager loads — use contains_eager for already-joined rels
        options = _join_info.eager_load_options(_model, explicitly_joined)
        if options:
            query = query.options(*options)

        result = await db.execute(query)
        rows = list(result.scalars().unique())

        _join_info.sort_o2m_collections(rows)

        if _config.after_query is not None:
            rows = await call_hook(_config.after_query, rows, request, current_user)

        data = [_schema.model_validate(row, from_attributes=True) for row in rows]

        return PaginatedResponse(
            data=data,
            total_count=total_count,
            has_more=(pagination.sql_offset + pagination.sql_limit) < total_count,
            page=pagination.page,
            items_per_page=pagination.items_per_page,
        )

    inject_query_params(_handler, _config.filterable_fields, _model, _join_info.joined_models)

    model_name = model.__name__
    deps = list(_config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, _config.permissions)))
    router.add_api_route(
        path,
        _handler,
        methods=["GET"],
        response_model=PaginatedResponse[_schema],
        response_model_by_alias=True,
        tags=_config.tags or None,
        summary=summary or f"List {model_name} rows from the database.",
        dependencies=deps,
        responses=get_error_responses(403),
    )
