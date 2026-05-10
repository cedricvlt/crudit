from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, selectinload

from crudit.joins import resolve_joins
from crudit.permissions import check_object_permissions, check_route_permissions, has_allowed_users_relationship
from crudit.read.endpoint import _detect_pk_field
from crudit.signature import patch_param_annotation
from crudit.types import PermissionDepFn
from crudit.unique_constraints import check_unique_constraints, detect_unique_constraints, integrity_error_to_http
from crudit.update.config import UpdateConfig
from crudit.utils import bind_perms, call_hook, get_error_responses, model_snake_name, user_dep_or_none


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

    Only fields present in the request body are applied (exclude_unset semantics).
    Join resolution for `read_schema` happens once at registration time.
    """
    join_info = resolve_joins(model, read_schema)
    pk_field = _detect_pk_field(model)
    _pk_python_type = list(sa_inspect(model).primary_key)[0].type.python_type
    load_allowed_users = (
        has_allowed_users_relationship(model)
        and "allowed_users" not in join_info.nodes
    )
    unique_specs = detect_unique_constraints(model)

    _model = model
    _update_schema = update_schema
    _read_schema = read_schema
    _config = config
    _join_info = join_info
    _pk_field = pk_field
    _unique_specs = unique_specs

    db_dep = Depends(get_db)
    user_dep = user_dep_or_none(login_dep)

    async def _handler(
        request: Request,
        id: Any,  # annotation patched below to _pk_python_type
        body: BaseModel,  # annotation patched below to _update_schema
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
    ) -> Any:
        # 1. Login check
        check_route_permissions(current_user, _config.login_required)

        # 2. Fetch existing object
        pk_col = getattr(_model, _pk_field)
        query = select(_model).where(pk_col == id)

        options = _join_info.eager_load_options(_model, set())
        if load_allowed_users:
            options.append(selectinload(getattr(_model, "allowed_users")))
        if options:
            query = query.options(*options)

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

        # 4. Build patch dict (only fields the client sent)
        patch_data: dict[str, Any] = body.model_dump(exclude_unset=True)

        # 5. Auto-fill updated_at when the column has no server_default
        mapper = sa_inspect(_model)
        if "updated_at" in mapper.columns:
            col = mapper.columns["updated_at"]
            if getattr(col, "server_default", None) is None:
                patch_data["updated_at"] = datetime.now(timezone.utc)

        # 6. Auto-fill updated_by from current_user.id
        if "updated_by" in mapper.columns and current_user is not None:
            user_id = getattr(current_user, "id", None)
            if user_id is not None:
                patch_data["updated_by"] = user_id

        # 7. Field setters (can be async)
        for field_name, setter in _config.field_setters.items():
            patch_data[field_name] = await call_hook(setter, obj, request, current_user)

        # 8. before_update hook — receives the existing obj and the full patch dict
        if _config.before_update is not None:
            patch_data = await call_hook(_config.before_update, obj, patch_data, request, current_user)

        # 9. Pre-flight unique constraint check using the post-patch values.
        # We check before mutating `obj` so the SELECT's implicit autoflush
        # doesn't try to push the dirty row into the DB and raise IntegrityError
        # itself.
        if _unique_specs:
            values = {c.key: getattr(obj, c.key) for c in mapper.columns}
            values.update(patch_data)
            await check_unique_constraints(
                db, _model, _unique_specs, values,
                exclude_pk=(_pk_field, id),
            )

        # 10. Apply patch to ORM object
        for attr, value in patch_data.items():
            setattr(obj, attr, value)

        # 11. Persist
        db.add(obj)
        try:
            await db.commit()
        except IntegrityError as err:
            await db.rollback()
            raise integrity_error_to_http(err, _unique_specs)

        # 12. Reload with eager-loaded relationships from read_schema
        reload_q = select(_model).where(pk_col == id)
        reload_options = _join_info.eager_load_options(_model, set())
        if reload_options:
            reload_q = reload_q.options(*reload_options)
        result = await db.execute(reload_q)
        obj = result.scalars().unique().one()

        # 13. after_update hook
        if _config.after_update is not None:
            obj = await call_hook(_config.after_update, obj, request, current_user)

        return _read_schema.model_validate(obj, from_attributes=True)

    patch_param_annotation(_handler, "id", _pk_python_type)
    patch_param_annotation(_handler, "body", _update_schema)

    model_name = model.__name__
    deps = list(_config.dependencies)
    if permission_dep is not None:
        deps.append(Depends(bind_perms(permission_dep, _config.permissions)))
    op_id = operation_id or _config.operation_id or f"update_{model_snake_name(model)}"
    router.add_api_route(
        path,
        _handler,
        methods=["PATCH"],
        response_model=_read_schema,
        status_code=200,
        tags=_config.tags or None,
        summary=summary or f"Update an existing {model_name} row in the database.",
        operation_id=op_id,
        dependencies=deps,
        responses=get_error_responses(400, *([401] if login_dep else []), 403, 404),
    )
