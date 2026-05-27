from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel
from sqlalchemy import func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from crudit.context import CruditContext
from crudit.exceptions import CruditConfigError
from crudit.joins import JoinInfo, collect_needed_joins, collect_sortable_field_paths, resolve_joins
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
from crudit.schemas import OffsetPaginatedResponse
from crudit.signature import inject_path_params, inject_query_params
from crudit.utils import bind_perms, call_hook, get_error_responses, model_snake_name, user_dep_or_none


class _DefaultOptionSchema(BaseModel):
    """Zero-config option schema: serialises to {id, label} with label from `name`."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: Any
    name: str = Field(exclude=True)

    @computed_field
    @property
    def label(self) -> str:
        return str(self.name)


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
    operation_id: str | None = None,
    schema: type[BaseModel] | None = None,
    get_db: Callable,
) -> None:
    """
    Register a paginated options GET endpoint on `router`.

    Rows are serialised with `schema`, which must expose a `label` field — either
    a plain field (e.g. ``label: str = Field(validation_alias="name")``) or a
    ``@computed_field`` built from other declared fields. The schema also drives
    join resolution, so any nested relationship fields it declares are
    eager-loaded.

    When `schema` is omitted, items are shaped as {id, label} with the label read
    from the model's `name` column. If the model has no `name` column, an explicit
    `schema` is required.
    """
    if schema is None and "name" not in inspect(model).columns:
        raise CruditConfigError(
            f"options_endpoint for {model.__name__} requires an explicit `schema` with a "
            "`label` field: no `schema` was given and the model has no `name` column to "
            "default the label from."
        )

    effective_schema = schema or _DefaultOptionSchema
    join_info: JoinInfo = resolve_joins(model, effective_schema)
    auto_sortable = collect_sortable_field_paths(model, effective_schema, join_info)
    config.sortable_fields = list(dict.fromkeys([*auto_sortable, *config.sortable_fields]))

    _model = model
    _config = config
    _join_info = join_info
    _schema = effective_schema
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
        explicitly_joined: set[str] = collect_needed_joins(
            filter_params, sort, _join_info, _config.search_fields
        )
        query = _join_info.apply_explicit_joins(query, _model, explicitly_joined)

        query = apply_search(
            query,
            q,
            _model,
            _join_info,
            _config.search_fields,
            _config.search_fn,
            current_user,
        )

        query = apply_filters(
            query,
            filter_params,
            _model,
            _join_info,
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
            _join_info,
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

        _join_info.sort_o2m_collections(rows)
        data = [_schema.model_validate(row, from_attributes=True) for row in rows]

        return OffsetPaginatedResponse(
            data=data,
            total_count=total_count,
            has_more=(pagination.sql_offset + pagination.sql_limit) < total_count,
        )

    inject_query_params(_handler, _config.filterable_fields, _model, _join_info)
    inject_path_params(_handler, _path_filters, _model)

    model_name = model.__name__
    deps = list(_config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, _config.permissions)))
    op_id = operation_id or _config.operation_id or f"list_{model_snake_name(model)}_options"
    router.add_api_route(
        path,
        _handler,
        methods=["GET"],
        response_model=OffsetPaginatedResponse[effective_schema],
        response_model_by_alias=True,
        tags=_config.tags or None,
        summary=summary or f"List {model_name} option items for selection.",
        operation_id=op_id,
        dependencies=deps,
        responses=get_error_responses(*([401] if login_dep else []), 403),
    )
