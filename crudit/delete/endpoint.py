from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, selectinload

from crudit.delete.config import DeleteConfig
from crudit.permissions import check_object_permissions, check_route_permissions, has_allowed_users_relationship
from crudit.read.endpoint import _detect_pk_field
from crudit.utils import call_hook, get_error_responses


def delete_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    config: DeleteConfig,
    *,
    get_db: Callable,
) -> None:
    """
    Register a DELETE endpoint that removes an existing object and returns 204 No Content.

    Row-level permission checks (tenant_id / allowed_users) are applied before deletion.
    """
    pk_field = _detect_pk_field(model)
    _pk_python_type = list(sa_inspect(model).primary_key)[0].type.python_type
    load_allowed_users = has_allowed_users_relationship(model)

    _model = model
    _config = config
    _pk_field = pk_field

    db_dep = Depends(get_db)
    user_dep = Depends(_config.login_dep) if _config.login_dep else None

    async def _handler(
        request: Request,
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
    ) -> Response:
        # 1. Login check
        check_route_permissions(current_user, _config.login_required)

        # 2. Fetch object
        pk_value = _pk_python_type(request.path_params["id"])
        pk_col = getattr(_model, _pk_field)
        query = select(_model).where(pk_col == pk_value)

        if load_allowed_users:
            query = query.options(selectinload(getattr(_model, "allowed_users")))

        result = await db.execute(query)
        obj = result.scalars().unique().one_or_none()

        if obj is None:
            raise HTTPException(status_code=404, detail="Not found.")

        # 3. Object-level permission check
        check_object_permissions(
            obj,
            _model,
            current_user,
            _config.login_required,
        )

        # 4. before_delete hook — can raise to abort
        if _config.before_delete is not None:
            await call_hook(_config.before_delete, obj, request, current_user)

        # 5. Delete and commit
        await db.delete(obj)
        await db.commit()

        # 6. after_delete hook — obj is detached but attributes are still accessible
        if _config.after_delete is not None:
            await call_hook(_config.after_delete, obj, request, current_user)

        return Response(status_code=204)

    model_name = model.__name__
    deps = list(_config.dependencies)
    if _config.permission_dep is not None and _config.permissions:
        deps.append(_config.permission_dep(_config.permissions))
    router.add_api_route(
        path,
        _handler,
        methods=["DELETE"],
        status_code=204,
        response_class=Response,
        tags=_config.tags or None,
        summary=_config.summary or f"Delete a {model_name} row from the database.",
        dependencies=deps,
        responses=get_error_responses(400, 403, 404),
    )
