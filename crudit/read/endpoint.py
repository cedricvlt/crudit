from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, selectinload

from crudit.exceptions import CruditConfigError
from crudit.joins import resolve_joins
from crudit.permissions import check_object_permissions, has_allowed_users_relationship
from crudit.read.config import ReadConfig
from crudit.types import PermissionDepFn
from crudit.signature import patch_param_annotation
from crudit.utils import bind_perms, call_hook, get_error_responses, user_dep_or_none


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
    """
    Register a single-object GET endpoint on `router`.

    The path must contain an `{id}` parameter. The primary key field is
    auto-detected from the SQLAlchemy mapper. Join resolution happens once
    at registration time.
    """
    join_info = resolve_joins(model, schema)
    pk_field = _detect_pk_field(model)
    _pk_python_type = list(sa_inspect(model).primary_key)[0].type.python_type
    load_allowed_users = (
        has_allowed_users_relationship(model)
        and "allowed_users" not in join_info.joined_models
    )

    _model = model
    _schema = schema
    _config = config
    _join_info = join_info
    _pk_field = pk_field

    db_dep = Depends(get_db)
    user_dep = user_dep_or_none(login_dep)

    async def _handler(
        request: Request,
        id: Any,  # annotation patched below to _pk_python_type
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
    ) -> Any:
        pk_col = getattr(_model, _pk_field)
        query = select(_model).where(pk_col == id)

        # Eager loads from schema-derived joins
        options = _join_info.eager_load_options(_model, set())
        # Always load allowed_users when needed for permission check
        if load_allowed_users:
            options.append(selectinload(getattr(_model, "allowed_users")))
        if options:
            query = query.options(*options)

        if _config.before_query is not None:
            query = await call_hook(_config.before_query, query, request, current_user)

        result = await db.execute(query)
        obj = result.scalars().unique().one_or_none()

        if obj is None:
            raise HTTPException(status_code=404, detail="Not found.")

        check_object_permissions(
            obj,
            _model,
            current_user,
            _config.login_required,
        )

        if _config.after_query is not None:
            obj = await call_hook(_config.after_query, obj, request, current_user)

        return _schema.model_validate(obj, from_attributes=True)

    patch_param_annotation(_handler, "id", _pk_python_type)

    model_name = model.__name__
    deps = list(_config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, _config.permissions)))
    router.add_api_route(
        path,
        _handler,
        methods=["GET"],
        response_model=_schema,
        tags=_config.tags or None,
        summary=summary or f"Retrieve a single {model_name} row from the database.",
        dependencies=deps,
        responses=get_error_responses(400, 403, 404),
    )


def _detect_pk_field(model: type[DeclarativeBase]) -> str:
    mapper = sa_inspect(model)
    pk_cols = list(mapper.primary_key)
    if len(pk_cols) != 1:
        raise CruditConfigError(
            f"{model.__name__} must have exactly one primary key column for read_endpoint."
        )
    return pk_cols[0].name
