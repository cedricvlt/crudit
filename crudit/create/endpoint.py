from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from crudit.context import CruditContext
from crudit.create.config import CreateConfig
from crudit.create.service import create_service
from crudit.exceptions import CruditNotFound, CruditValidationError
from crudit.foreign_keys import detect_foreign_keys
from crudit.joins import resolve_joins
from crudit.read.endpoint import detect_pk_field
from crudit.signature import inject_path_params, patch_param_annotation
from crudit.types import PermissionDepFn
from crudit.unique_constraints import detect_unique_constraints
from crudit.utils import bind_perms, get_error_responses, model_snake_name, user_dep_or_none


def _strip_path_filter_fields(
    create_schema: type[BaseModel],
    path_filters: dict[str, str],
) -> type[BaseModel]:
    """Return a derived pydantic model with the path-filter target fields
    removed so they no longer appear in the request body schema."""
    from pydantic import create_model

    excluded = set(path_filters.values())
    fields_in_schema = create_schema.model_fields
    if not (excluded & fields_in_schema.keys()):
        return create_schema

    new_fields: dict[str, Any] = {
        name: (info.annotation, info)
        for name, info in fields_in_schema.items()
        if name not in excluded
    }
    return create_model(  # type: ignore[call-overload]
        create_schema.__name__,
        __base__=BaseModel,
        **new_fields,
    )


def create_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    create_schema: type[BaseModel],
    read_schema: type[BaseModel],
    config: CreateConfig,
    *,
    path_filters: dict[str, str] | None = None,
    login_dep: Callable | None = None,
    permission_dep: PermissionDepFn | None = None,
    summary: str | None = None,
    operation_id: str | None = None,
    get_db: Callable,
) -> None:
    """
    Register a POST endpoint that creates a new object and returns it serialised
    as `read_schema` with status 201.

    Thin wrapper around `create_service`. Join resolution for `read_schema`
    happens once at registration time.

    `path_filters` maps a URL path param onto a model field. The matching
    field is removed from the request body schema and the value is auto-
    injected from the URL when the object is built — e.g. with
    ``path_filters={"city_id": "city_id"}`` and path ``/cities/{city_id}/districts``,
    ``city_id`` is read from the URL and clients omit it from the body.
    """
    join_info = resolve_joins(model, read_schema)
    pk_field = detect_pk_field(model)
    _path_filters: dict[str, str] = path_filters or {}
    _body_schema = _strip_path_filter_fields(create_schema, _path_filters)
    unique_specs = detect_unique_constraints(model)
    fk_specs = detect_foreign_keys(model)

    db_dep = Depends(get_db)
    user_dep = user_dep_or_none(login_dep)

    async def _handler(
        request: Request,
        body: BaseModel,  # annotation patched below to _body_schema
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
        **_path_kwargs,  # absorbs path-filter params injected via __signature__
    ) -> Any:
        ctx = CruditContext(
            user=current_user,
            path_params=dict(request.path_params),
            query_params=dict(request.query_params),
            request=request,
        )
        try:
            return await create_service(
                db,
                ctx,
                model=model,
                body=body,
                read_schema=read_schema,
                config=config,
                path_filters=_path_filters,
                join_info=join_info,
                pk_field=pk_field,
                unique_specs=unique_specs,
                fk_specs=fk_specs,
            )
        except CruditNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except CruditValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    patch_param_annotation(_handler, "body", _body_schema)
    inject_path_params(_handler, _path_filters, model)

    model_name = model.__name__
    deps = list(config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, config.permissions)))
    op_id = operation_id or config.operation_id or f"create_{model_snake_name(model)}"
    router.add_api_route(
        path,
        _handler,
        methods=["POST"],
        response_model=read_schema,
        status_code=201,
        tags=config.tags or None,
        summary=summary or f"Create a new {model_name} row in the database.",
        operation_id=op_id,
        dependencies=deps,
        responses=get_error_responses(400, *([401] if login_dep else []), 403, 404),
    )
