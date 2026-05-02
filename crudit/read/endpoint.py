from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from crudit.context import CruditContext
from crudit.exceptions import CruditNotFound
from crudit.joins import resolve_joins
from crudit.read.config import ReadConfig
from crudit.read.service import detect_pk_field, read_service
from crudit.signature import patch_param_annotation
from crudit.types import PermissionDepFn
from crudit.utils import bind_perms, get_error_responses, user_dep_or_none

# Backwards-compatible alias — other endpoint modules still import this name.
_detect_pk_field = detect_pk_field


def read_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    schema: type[BaseModel],
    config: ReadConfig,
    *,
    login_dep: Callable | None = None,
    permission_dep: PermissionDepFn | None = None,
    summary: str | None = None,
    get_db: Callable,
) -> None:
    """Register a single-object GET endpoint on `router`.

    Thin wrapper around `read_service`. Translates `CruditNotFound` to HTTP 404.
    Join resolution and PK detection happen once at registration time.
    """
    join_info = resolve_joins(model, schema)
    pk_field = detect_pk_field(model)
    pk_python_type = list(sa_inspect(model).primary_key)[0].type.python_type

    db_dep = Depends(get_db)
    user_dep = user_dep_or_none(login_dep)

    async def _handler(
        request: Request,
        id: Any,  # annotation patched below to pk_python_type
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
            return await read_service(
                db,
                ctx,
                model=model,
                schema=schema,
                config=config,
                id=id,
                join_info=join_info,
                pk_field=pk_field,
            )
        except CruditNotFound:
            raise HTTPException(status_code=404, detail="Not found.")

    patch_param_annotation(_handler, "id", pk_python_type)

    model_name = model.__name__
    deps = list(config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, config.permissions)))
    router.add_api_route(
        path,
        _handler,
        methods=["GET"],
        response_model=schema,
        tags=config.tags or None,
        summary=summary or f"Retrieve a single {model_name} row from the database.",
        dependencies=deps,
        responses=get_error_responses(400, 403, 404),
    )
