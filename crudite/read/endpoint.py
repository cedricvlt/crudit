from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, selectinload

from crudite.exceptions import CruditeConfigError
from crudite.list.joins import resolve_joins
from crudite.list.permissions import _has_allowed_users_relationship, check_object_permissions
from crudite.read.config import ReadConfig


def read_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    schema: type[BaseModel],
    config: ReadConfig,
    *,
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
    load_allowed_users = (
        _has_allowed_users_relationship(model)
        and "allowed_users" not in join_info.joined_models
    )

    _model = model
    _schema = schema
    _config = config
    _join_info = join_info
    _pk_field = pk_field

    db_dep = Depends(get_db)
    user_dep = Depends(_config.login_dep) if _config.login_dep else None

    async def _handler(
        request: Request,
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
    ) -> Any:
        pk_value = request.path_params.get("id")
        if pk_value is None:
            raise HTTPException(status_code=400, detail="Missing path param 'id'.")

        pk_col = getattr(_model, _pk_field)
        query = select(_model).where(pk_col == pk_value)

        # Eager loads from schema-derived joins
        options = _join_info.eager_load_options(_model, set())
        # Always load allowed_users when needed for permission check
        if load_allowed_users:
            options.append(selectinload(getattr(_model, "allowed_users")))
        if options:
            query = query.options(*options)

        # before_query hook
        if _config.before_query is not None:
            if asyncio.iscoroutinefunction(_config.before_query):
                query = await _config.before_query(query, request, current_user)
            else:
                query = _config.before_query(query, request, current_user)

        result = await db.execute(query)
        obj = result.scalars().unique().one_or_none()

        if obj is None:
            raise HTTPException(status_code=404, detail="Not found.")

        check_object_permissions(
            obj,
            _model,
            current_user,
            _config.login_required,
            _config.permissions,
            _config.permission_checker,
        )

        # after_query hook
        if _config.after_query is not None:
            if asyncio.iscoroutinefunction(_config.after_query):
                obj = await _config.after_query(obj, request, current_user)
            else:
                obj = _config.after_query(obj, request, current_user)

        return _schema.model_validate(obj, from_attributes=True)

    router.add_api_route(
        path,
        _handler,
        methods=["GET"],
        response_model=_schema,
        tags=_config.tags or None,
        summary=_config.summary,
        dependencies=list(_config.dependencies),
    )


def _detect_pk_field(model: type[DeclarativeBase]) -> str:
    mapper = sa_inspect(model)
    pk_cols = list(mapper.primary_key)
    if len(pk_cols) != 1:
        raise CruditeConfigError(
            f"{model.__name__} must have exactly one primary key column for read_endpoint."
        )
    return pk_cols[0].name
