from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, selectinload

from crudit.delete.config import DeleteConfig
from crudit.permissions import check_object_permissions, check_route_permissions, has_allowed_users_relationship
from crudit.read.endpoint import _detect_pk_field
from crudit.types import PermissionDepFn
from crudit.signature import patch_param_annotation
from crudit.utils import bind_perms, call_hook, get_error_responses, model_snake_name, user_dep_or_none


def delete_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    config: DeleteConfig,
    *,
    login_dep: Callable | None = None,
    permission_dep: PermissionDepFn | None = None,
    summary: str | None = None,
    operation_id: str | None = None,
    get_db: Callable,
) -> None:
    """
    Register a DELETE endpoint that removes an existing object and returns 204 No Content.

    Row-level permission checks (company_id / allowed_users) are applied before deletion.
    """
    pk_field = _detect_pk_field(model)
    _pk_python_type = list(sa_inspect(model).primary_key)[0].type.python_type
    load_allowed_users = has_allowed_users_relationship(model)

    _model = model
    _config = config
    _pk_field = pk_field

    db_dep = Depends(get_db)
    user_dep = user_dep_or_none(login_dep)

    async def _handler(
        request: Request,
        id: Any,  # annotation patched below to _pk_python_type
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
    ) -> Response:
        # 1. Login check
        check_route_permissions(current_user, _config.login_required)

        # 2. Fetch object
        pk_col = getattr(_model, _pk_field)
        query = select(_model).where(pk_col == id)

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

    patch_param_annotation(_handler, "id", _pk_python_type)

    model_name = model.__name__
    deps = list(_config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, _config.permissions)))
    op_id = operation_id or _config.operation_id or f"delete_{model_snake_name(model)}"
    router.add_api_route(
        path,
        _handler,
        methods=["DELETE"],
        status_code=204,
        response_class=Response,
        tags=_config.tags or None,
        summary=summary or f"Delete a {model_name} row from the database.",
        operation_id=op_id,
        dependencies=deps,
        responses=get_error_responses(400, *([401] if login_dep else []), 403, 404),
    )
