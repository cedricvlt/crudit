from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, selectinload

from crudit.list.filters import apply_path_filters
from crudit.permissions import check_object_permissions, check_route_permissions, has_allowed_users_relationship
from crudit.read.endpoint import _detect_pk_field
from crudit.reorder.config import ReorderConfig
from crudit.signature import inject_path_params
from crudit.types import PermissionDepFn
from crudit.utils import bind_perms, call_hook, get_error_responses, user_dep_or_none

_ORDER_FIELD = "sort_order"


class _ReorderBody(BaseModel):
    ids: list[Any]


def reorder_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    config: ReorderConfig,
    *,
    path_filters: dict[str, str] | None = None,
    login_dep: Callable | None = None,
    permission_dep: PermissionDepFn | None = None,
    summary: str | None = None,
    get_db: Callable,
) -> None:
    """
    Register a POST endpoint that reorders objects by assigning sort_order = position index.

    Validates existence and permissions for every requested ID before committing.
    Path filters are applied to scope the query (same as list_endpoint).
    Join resolution and model validation happen here (once), not per-request.
    """
    if not hasattr(model, _ORDER_FIELD):
        raise ValueError(
            f"Model {model.__name__!r} has no '{_ORDER_FIELD}' column. "
            "Add a sort_order column to use reorder_endpoint."
        )

    pk_field = _detect_pk_field(model)
    load_allowed_users = has_allowed_users_relationship(model)

    _model = model
    _config = config
    _pk_field = pk_field
    _path_filters: dict[str, str] = path_filters or {}

    db_dep = Depends(get_db)
    user_dep = user_dep_or_none(login_dep)

    async def _handler(
        request: Request,
        body: _ReorderBody,
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
        **_path_kwargs,  # absorbs path-filter params injected via __signature__
    ) -> Response:
        # 1. Login check
        check_route_permissions(current_user, _config.login_required)

        # 2. Empty input — nothing to reorder
        if not body.ids:
            return Response(status_code=204)

        # 3. Fetch all requested objects, scoped by path filters
        pk_col = getattr(_model, _pk_field)
        path_params = dict(request.path_params)

        query = select(_model).where(pk_col.in_(body.ids))
        query = apply_path_filters(query, _model, _path_filters, path_params)

        if load_allowed_users:
            query = query.options(selectinload(getattr(_model, "allowed_users")))

        result = await db.execute(query)
        objects_by_id: dict[Any, Any] = {
            getattr(obj, _pk_field): obj for obj in result.scalars().unique()
        }

        # 4. Existence check — 404 if any ID is absent or filtered out by path_filters
        missing = [id_ for id_ in body.ids if id_ not in objects_by_id]
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"Object(s) not found: {missing}.",
            )

        # 5. Row-level permission check — 403 for inaccessible objects
        for obj in objects_by_id.values():
            check_object_permissions(
                obj,
                _model,
                current_user,
                _config.login_required,
            )

        ordered_objects = [objects_by_id[id_] for id_ in body.ids]

        # 6. before_reorder hook
        if _config.before_reorder is not None:
            await call_hook(_config.before_reorder, ordered_objects, request, current_user)

        # 7. Assign sort_order by position (0-based)
        for position, obj in enumerate(ordered_objects):
            setattr(obj, _ORDER_FIELD, position)

        await db.commit()

        # 8. after_reorder hook
        if _config.after_reorder is not None:
            await call_hook(_config.after_reorder, ordered_objects, request, current_user)

        return Response(status_code=204)

    inject_path_params(_handler, _path_filters, _model)

    model_name = model.__name__
    deps = list(_config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, _config.permissions)))
    router.add_api_route(
        path,
        _handler,
        methods=["POST"],
        status_code=204,
        response_class=Response,
        tags=_config.tags or None,
        summary=summary or f"Reorder {model_name} rows by providing an ordered list of IDs.",
        dependencies=deps,
        responses=get_error_responses(403, 404),
    )
