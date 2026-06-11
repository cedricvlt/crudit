from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from crudit.context import CruditContext
from crudit.delete.config import DeleteConfig
from crudit.delete.service import delete_service
from crudit.exceptions import CruditNotFound
from crudit.read.endpoint import detect_pk_field
from crudit.signature import patch_param_annotation
from crudit.types import PermissionDepFn
from crudit.utils import bind_perms, get_error_responses, model_snake_name, user_dep_or_none


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

    Thin wrapper around `delete_service`. Row-level permission checks
    (company_id / allowed_users) are applied before deletion.
    """
    pk_field = detect_pk_field(model)
    _pk_python_type = list(sa_inspect(model).primary_key)[0].type.python_type

    db_dep = Depends(get_db)
    user_dep = user_dep_or_none(login_dep)

    async def _handler(
        request: Request,
        id: Any,  # annotation patched below to _pk_python_type
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
    ) -> Response:
        ctx = CruditContext(
            user=current_user,
            path_params=dict(request.path_params),
            query_params=dict(request.query_params),
            request=request,
        )
        try:
            await delete_service(
                db,
                ctx,
                model=model,
                config=config,
                id=id,
                pk_field=pk_field,
            )
        except CruditNotFound:
            raise HTTPException(status_code=404, detail="Not found.")
        return Response(status_code=204)

    patch_param_annotation(_handler, "id", _pk_python_type)

    model_name = model.__name__
    deps = list(config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, config.permissions)))
    op_id = operation_id or config.operation_id or f"delete_{model_snake_name(model)}"
    router.add_api_route(
        path,
        _handler,
        methods=["DELETE"],
        status_code=204,
        response_class=Response,
        tags=config.tags or None,
        summary=summary or f"Delete a {model_name} row from the database.",
        operation_id=op_id,
        dependencies=deps,
        responses=get_error_responses(400, *([401] if login_dep else []), 403, 404),
    )
