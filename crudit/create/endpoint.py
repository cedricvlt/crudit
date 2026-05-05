from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, selectinload

from crudit.create.config import CreateConfig
from crudit.joins import resolve_joins
from crudit.permissions import check_object_permissions, check_route_permissions, has_allowed_users_relationship
from crudit.types import PermissionDepFn
from crudit.read.endpoint import _detect_pk_field
from crudit.signature import inject_path_params, patch_param_annotation
from crudit.utils import bind_perms, call_hook, get_error_responses, user_dep_or_none


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
    get_db: Callable,
) -> None:
    """
    Register a POST endpoint that creates a new object and returns it serialised
    as `read_schema` with status 201.

    Join resolution for `read_schema` happens once at registration time.

    `path_filters` maps a URL path param onto a model field. The matching
    field is removed from the request body schema and the value is auto-
    injected from the URL when the object is built — e.g. with
    ``path_filters={"city_id": "city_id"}`` and path ``/cities/{city_id}/districts``,
    ``city_id`` is read from the URL and clients omit it from the body.
    """
    join_info = resolve_joins(model, read_schema)
    pk_field = _detect_pk_field(model)
    _path_filters: dict[str, str] = path_filters or {}
    _body_schema = _strip_path_filter_fields(create_schema, _path_filters)

    _model = model
    _create_schema = _body_schema
    _read_schema = read_schema
    _config = config
    _join_info = join_info
    _pk_field = pk_field

    db_dep = Depends(get_db)
    user_dep = user_dep_or_none(login_dep)

    async def _handler(
        request: Request,
        body: BaseModel,  # annotation patched below to _create_schema
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
        **_path_kwargs,  # absorbs path-filter params injected via __signature__
    ) -> Any:
        # 1. Login check
        check_route_permissions(current_user, _config.login_required)

        # 2. Resolve parents: existence check + row-level permission on each parent
        parent_values: dict[str, Any] = {}
        for pp in _config.parent_params:
            url_value = request.path_params.get(pp.url_param)
            if url_value is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing path parameter '{pp.url_param}'.",
                )
            parent_pk = _detect_pk_field(pp.model)
            pk_col = getattr(pp.model, parent_pk)
            q = select(pp.model).where(pk_col == url_value)
            if has_allowed_users_relationship(pp.model):
                q = q.options(selectinload(getattr(pp.model, "allowed_users")))
            result = await db.execute(q)
            parent = result.scalars().unique().one_or_none()
            if parent is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"{pp.model.__name__} with id {url_value!r} not found.",
                )
            check_object_permissions(
                parent,
                pp.model,
                current_user,
                _config.login_required,
            )
            parent_values[pp.child_field] = url_value

        # 3. Build ORM object from validated body
        obj = _model(**body.model_dump())

        # 4. Set parent FK fields (override anything in body)
        for child_field, value in parent_values.items():
            setattr(obj, child_field, value)

        # 4b. Apply path_filters: copy URL value onto the mapped model field
        for url_param, model_field in _path_filters.items():
            url_value = request.path_params.get(url_param)
            if url_value is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing path parameter '{url_param}'.",
                )
            setattr(obj, model_field, url_value)

        # 5. Auto-fill created_at when the column has no server_default
        mapper = sa_inspect(_model)
        if "created_at" in mapper.columns:
            col = mapper.columns["created_at"]
            if getattr(col, "server_default", None) is None:
                obj.created_at = datetime.now(timezone.utc)

        # 6. Auto-fill created_by from current_user.id
        if "created_by" in mapper.columns and current_user is not None:
            user_id = getattr(current_user, "id", None)
            if user_id is not None:
                obj.created_by = user_id

        # 7. Field setters (can be async)
        for field_name, setter in _config.field_setters.items():
            setattr(obj, field_name, await call_hook(setter, obj, request, current_user))

        # 8. before_create hook
        if _config.before_create is not None:
            obj = await call_hook(_config.before_create, obj, request, current_user)

        # 9. Persist
        db.add(obj)
        await db.commit()

        # 10. Reload with eager-loaded relationships from read_schema
        pk_col = getattr(_model, _pk_field)
        pk_value = getattr(obj, _pk_field)
        reload_q = select(_model).where(pk_col == pk_value)
        options = _join_info.eager_load_options(_model, set())
        if options:
            reload_q = reload_q.options(*options)
        result = await db.execute(reload_q)
        obj = result.scalars().unique().one()

        # 11. after_create hook
        if _config.after_create is not None:
            obj = await call_hook(_config.after_create, obj, request, current_user)

        return _read_schema.model_validate(obj, from_attributes=True)

    patch_param_annotation(_handler, "body", _create_schema)
    inject_path_params(_handler, _path_filters, _model)

    model_name = model.__name__
    deps = list(_config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, _config.permissions)))
    router.add_api_route(
        path,
        _handler,
        methods=["POST"],
        response_model=_read_schema,
        status_code=201,
        tags=_config.tags or None,
        summary=summary or f"Create a new {model_name} row in the database.",
        dependencies=deps,
        responses=get_error_responses(400, *([401] if login_dep else []), 403, 404),
    )
