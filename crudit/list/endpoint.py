from __future__ import annotations

from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from crudit.context import CruditContext
from crudit.joins import resolve_joins
from crudit.list.config import ListConfig
from crudit.list.filters import extract_filter_params
from crudit.list.service import list_service
from crudit.permissions import apply_permissions  # noqa: F401  (kept for re-export compat)
from crudit.schemas import PaginatedResponse
from crudit.signature import inject_path_params, inject_query_params
from crudit.types import PermissionDepFn
from crudit.utils import bind_perms, get_error_responses, model_snake_name, user_dep_or_none


def list_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    schema: type[BaseModel],
    config: ListConfig,
    *,
    path_filters: dict[str, str] | None = None,
    login_dep: Callable | None = None,
    permission_dep: PermissionDepFn | None = None,
    summary: str | None = None,
    operation_id: str | None = None,
    get_db: Callable,
) -> None:
    """Register a paginated list GET endpoint on `router`.

    The handler is a thin wrapper that builds a `CruditContext` from the
    Starlette request and delegates the actual work to `list_service`. Join
    resolution and config validation happen here (once), not per-request.
    """
    join_info = resolve_joins(model, schema)
    _path_filters: dict[str, str] = path_filters or {}

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
        ctx = CruditContext(
            user=current_user,
            path_params=dict(request.path_params),
            query_params=dict(request.query_params),
            request=request,
        )
        result = await list_service(
            db,
            ctx,
            model=model,
            schema=schema,
            config=config,
            path_filters=_path_filters,
            join_info=join_info,
            q=q,
            sort=sort,
            page=page,
            items_per_page=items_per_page,
            offset=offset,
            limit=limit,
            count_only=count_only,
            filter_params=extract_filter_params(request.query_params),
        )
        if count_only:
            return JSONResponse({"totalCount": result})
        return result

    inject_query_params(_handler, config.filterable_fields, model, join_info.joined_models)
    inject_path_params(_handler, _path_filters, model)

    model_name = model.__name__
    deps = list(config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, config.permissions)))
    op_id = operation_id or config.operation_id or f"list_{model_snake_name(model)}"
    router.add_api_route(
        path,
        _handler,
        methods=["GET"],
        response_model=PaginatedResponse[schema],
        response_model_by_alias=True,
        tags=config.tags or None,
        summary=summary or f"List {model_name} rows from the database.",
        operation_id=op_id,
        dependencies=deps,
        responses=get_error_responses(*([401] if login_dep else []), 403),
    )
