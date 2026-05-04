from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from crudit.context import CruditContext
from crudit.exceptions import CruditConfigError
from crudit.joins import JoinInfo, collect_needed_joins, resolve_joins
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
from crudit.options.config import OptionsConfig
from crudit.permissions import apply_permissions
from crudit.schemas import OffsetPaginatedResponse, OptionItem
from crudit.signature import inject_path_params, inject_query_params
from crudit.utils import bind_perms, call_hook, get_error_responses, user_dep_or_none


class _DefaultOptionSchema(BaseModel):
    name: str


def options_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    config: OptionsConfig,
    *,
    path_filters: dict[str, str] | None = None,
    login_dep: Callable | None = None,
    permission_dep: PermissionDepFn | None = None,
    summary: str | None = None,
    schema: type[BaseModel] = _DefaultOptionSchema,
    get_db: Callable,
) -> None:
    """
    Register a paginated options GET endpoint on `router`.

    Returns items shaped as {id, label}. The label comes from either
    config.label_field (a column name) or config.label_fn (a callable that
    receives the ORM row and returns a str).

    Pass `schema` when label_fn or filters/sort need related objects — it is
    used solely for join resolution, not for serialisation. Defaults to a
    minimal schema with only a `name` field.
    """
    if config.label_field is None and config.label_fn is None:
        config.label_field = "name"
    elif config.label_field is not None and config.label_fn is not None:
        raise CruditConfigError(
            "OptionsConfig requires either label_field or label_fn, not both."
        )

    join_info: JoinInfo = resolve_joins(model, schema)

    _model = model
    _config = config
    _join_info = join_info
    _path_filters: dict[str, str] = path_filters or {}

    db_dep = Depends(get_db)
    user_dep = user_dep_or_none(login_dep)

    async def _handler(
        request: Request,
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
        q: str | None = None,
        sort: str | None = None,
        offset: int | None = None,
        limit: int | None = None,
        **_filter_kwargs,  # absorbs filterable-field params injected via __signature__
    ) -> Any:
        filter_params = extract_filter_params(request.query_params)
        path_params = dict(request.path_params)
        ctx = CruditContext(
            user=current_user,
            path_params=path_params,
            query_params=dict(request.query_params),
            request=request,
        )

        query = select(_model)
        query = apply_path_filters(query, _model, _path_filters, path_params)
        query = apply_default_filters(query, _model, _config.default_filters)
        query = apply_permissions(
            query,
            _model,
            current_user,
            _config.login_required,
        )
        query = apply_search(
            query,
            q,
            _model,
            _join_info.joined_models,
            _config.search_fields,
            _config.search_fn,
            current_user,
        )

        explicitly_joined: set[str] = collect_needed_joins(
            filter_params, sort, _join_info
        )
        for rel_name in explicitly_joined:
            rel_attr = getattr(_model, rel_name)
            query = query.join(rel_attr, isouter=True)

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
            query = await call_hook(_config.before_query, query, ctx)

        # COUNT (before sort/pagination)
        count_query = select(func.count()).select_from(query.subquery())
        total_count = (await db.execute(count_query)).scalar_one()

        query = apply_sort(
            query,
            sort,
            _model,
            _join_info.joined_models,
            _config.sortable_fields,
        )

        pagination = resolve_pagination(None, None, offset, limit)
        query = apply_pagination(query, pagination)

        options = _join_info.eager_load_options(_model, explicitly_joined)
        if options:
            query = query.options(*options)

        result = await db.execute(query)
        rows = list(result.scalars().unique())

        if _config.after_query is not None:
            rows = await call_hook(_config.after_query, rows, ctx)

        data = [_build_item(row, _config) for row in rows]

        return OffsetPaginatedResponse(
            data=data,
            total_count=total_count,
            has_more=(pagination.sql_offset + pagination.sql_limit) < total_count,
        )

    inject_query_params(_handler, _config.filterable_fields, _model, _join_info.joined_models)
    inject_path_params(_handler, _path_filters, _model)

    model_name = model.__name__
    deps = list(_config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, _config.permissions)))
    router.add_api_route(
        path,
        _handler,
        methods=["GET"],
        response_model=OffsetPaginatedResponse[OptionItem],
        response_model_by_alias=True,
        tags=_config.tags or None,
        summary=summary or f"List {model_name} option items for selection.",
        dependencies=deps,
        responses=get_error_responses(403),
    )


def _build_item(row: Any, config: OptionsConfig) -> OptionItem:
    if config.label_fn is not None:
        label = str(config.label_fn(row))
    else:
        label = str(getattr(row, config.label_field, "") or "")
    return OptionItem(id=row.id, label=label)
