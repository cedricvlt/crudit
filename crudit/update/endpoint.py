from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from crudit.context import CruditContext
from crudit.exceptions import CruditNotFound
from crudit.foreign_keys import detect_foreign_keys
from crudit.joins import resolve_joins
from crudit.read.endpoint import detect_pk_field
from crudit.signature import patch_param_annotation
from crudit.types import PermissionDepFn
from crudit.unique_constraints import detect_unique_constraints
from crudit.update.config import UpdateConfig
from crudit.update.service import update_service
from crudit.utils import bind_perms, get_error_responses, model_snake_name, user_dep_or_none


def update_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    update_schema: type[BaseModel],
    read_schema: type[BaseModel],
    config: UpdateConfig,
    *,
    login_dep: Callable | None = None,
    permission_dep: PermissionDepFn | None = None,
    summary: str | None = None,
    operation_id: str | None = None,
    get_db: Callable,
) -> None:
    """
    Register a PATCH endpoint that partially updates an existing object and returns
    it serialised as `read_schema` with status 200.

    Thin wrapper around `update_service`. Only fields present in the request body
    are applied (exclude_unset semantics). Join resolution for `read_schema`
    happens once at registration time.
    """
    join_info = resolve_joins(model, read_schema)
    pk_field = detect_pk_field(model)
    _pk_python_type = list(sa_inspect(model).primary_key)[0].type.python_type
    unique_specs = detect_unique_constraints(model)
    fk_specs = detect_foreign_keys(model)

    db_dep = Depends(get_db)
    user_dep = user_dep_or_none(login_dep)

    async def _handler(
        request: Request,
        id: Any,  # annotation patched below to _pk_python_type
        body: BaseModel,  # annotation patched below to update_schema
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
    ) -> Any:
        ctx = CruditContext(
            user=current_user,
            path_params=dict(request.path_params),
            query_params=dict(request.query_params),
            request=request,
        )
        try:
            return await update_service(
                db,
                ctx,
                model=model,
                body=body,
                read_schema=read_schema,
                config=config,
                id=id,
                join_info=join_info,
                pk_field=pk_field,
                unique_specs=unique_specs,
                fk_specs=fk_specs,
            )
        except CruditNotFound:
            raise HTTPException(status_code=404, detail="Not found.")

    patch_param_annotation(_handler, "id", _pk_python_type)
    patch_param_annotation(_handler, "body", update_schema)

    model_name = model.__name__
    deps = list(config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, config.permissions)))
    op_id = operation_id or config.operation_id or f"update_{model_snake_name(model)}"
    router.add_api_route(
        path,
        _handler,
        methods=["PATCH"],
        response_model=read_schema,
        status_code=200,
        tags=config.tags or None,
        summary=summary or f"Update an existing {model_name} row in the database.",
        operation_id=op_id,
        dependencies=deps,
        responses=get_error_responses(400, *([401] if login_dep else []), 403, 404),
    )
