from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from crudit.exceptions import CruditConfigError
from crudit.joins import JoinInfo, collect_needed_joins, resolve_joins
from crudit.list.filters import apply_default_filters, apply_filters
from crudit.list.pagination import apply_pagination, resolve_pagination
from crudit.list.search import apply_search
from crudit.list.sort import apply_sort
from crudit.options.config import OptionsConfig
from crudit.permissions import apply_permissions
from crudit.schemas import OptionItem, PaginatedResponse


def options_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    config: OptionsConfig,
    *,
    schema: type[BaseModel] | None = None,
    get_db: Callable,
) -> None:
    """
    Register a paginated options GET endpoint on `router`.

    Returns items shaped as {id, label}. The label comes from either
    config.label_field (a column name) or config.label_fn (a callable that
    receives the ORM row and returns a str).

    Pass `schema` only when label_fn or filters/sort need related objects —
    it is used solely for join resolution, not for serialisation.
    """
    if config.label_field is None and config.label_fn is None:
        raise CruditConfigError(
            "OptionsConfig requires either label_field or label_fn."
        )
    if config.label_field is not None and config.label_fn is not None:
        raise CruditConfigError(
            "OptionsConfig requires either label_field or label_fn, not both."
        )

    join_info: JoinInfo = resolve_joins(model, schema) if schema is not None else JoinInfo()

    _model = model
    _config = config
    _join_info = join_info

    db_dep = Depends(get_db)
    user_dep = Depends(_config.login_dep) if _config.login_dep else None

    async def _handler(
        request: Request,
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
    ) -> Any:
        raw_params = dict(request.query_params)
        path_params = dict(request.path_params)

        sort_param = raw_params.get("sort")
        q_param = raw_params.get("q")

        page = _int_or_none(raw_params.get("page"))
        items_per_page = _int_or_none(raw_params.get("items_per_page"))
        offset = _int_or_none(raw_params.get("offset"))
        limit = _int_or_none(raw_params.get("limit"))

        query = select(_model)

        # Path filters
        for param_name, field_name in _config.path_filters.items():
            value = path_params.get(param_name)
            if value is None:
                raise HTTPException(
                    status_code=400, detail=f"Missing path param '{param_name}'."
                )
            col = getattr(_model, field_name, None)
            if col is None:
                raise HTTPException(
                    status_code=500, detail=f"Model field '{field_name}' not found."
                )
            query = query.where(col == value)

        # Default filters
        query = apply_default_filters(query, _model, _config.default_filters)

        # Permissions
        query = apply_permissions(
            query,
            _model,
            current_user,
            _config.login_required,
            _config.permissions,
            _config.permission_checker,
        )

        # Search
        query = apply_search(
            query,
            q_param,
            _model,
            _join_info.joined_models,
            _config.search_fields,
            _config.search_fn,
            current_user,
        )

        # Explicit joins needed for nested filter/sort columns
        explicitly_joined: set[str] = collect_needed_joins(
            raw_params, sort_param, _join_info
        )
        for rel_name in explicitly_joined:
            rel_attr = getattr(_model, rel_name)
            query = query.join(rel_attr, isouter=True)

        # User filters
        query = apply_filters(
            query,
            raw_params,
            _model,
            _join_info.joined_models,
            _config.filterable_fields,
            _config.filter_fns,
            current_user,
        )

        # before_query hook
        if _config.before_query is not None:
            if asyncio.iscoroutinefunction(_config.before_query):
                query = await _config.before_query(query, request, current_user)
            else:
                query = _config.before_query(query, request, current_user)

        # COUNT (before sort/pagination)
        count_query = select(func.count()).select_from(query.subquery())
        total_count = (await db.execute(count_query)).scalar_one()

        # Sort
        query = apply_sort(
            query,
            sort_param,
            _model,
            _join_info.joined_models,
            _config.sortable_fields,
        )

        # Pagination
        pagination = resolve_pagination(page, items_per_page, offset, limit)
        query = apply_pagination(query, pagination)

        # Eager loads
        options = _join_info.eager_load_options(_model, explicitly_joined)
        if options:
            query = query.options(*options)

        result = await db.execute(query)
        rows = list(result.scalars().unique())

        # after_query hook
        if _config.after_query is not None:
            if asyncio.iscoroutinefunction(_config.after_query):
                rows = await _config.after_query(rows, request, current_user)
            else:
                rows = _config.after_query(rows, request, current_user)

        # Build option items
        data = [_build_item(row, _config) for row in rows]

        return PaginatedResponse(
            data=data,
            total_count=total_count,
            has_more=(pagination.sql_offset + pagination.sql_limit) < total_count,
            page=pagination.page,
            items_per_page=pagination.items_per_page,
        )

    router.add_api_route(
        path,
        _handler,
        methods=["GET"],
        response_model=PaginatedResponse[OptionItem],
        tags=_config.tags or None,
        summary=_config.summary,
        dependencies=list(_config.dependencies),
    )


def _build_item(row: Any, config: OptionsConfig) -> OptionItem:
    if config.label_fn is not None:
        label = str(config.label_fn(row))
    else:
        label = str(getattr(row, config.label_field, "") or "")
    return OptionItem(id=row.id, label=label)


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
