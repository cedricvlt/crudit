from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, selectinload

from crudit.joins import resolve_joins
from crudit.permissions import check_object_permissions, has_allowed_users_relationship
from crudit.read.endpoint import _detect_pk_field
from crudit.update.config import UpdateConfig


def update_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    update_schema: type[BaseModel],
    read_schema: type[BaseModel],
    config: UpdateConfig,
    *,
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
    load_allowed_users = (
        has_allowed_users_relationship(model)
        and "allowed_users" not in join_info.joined_models
    )

    _model = model
    _update_schema = update_schema
    _read_schema = read_schema
    _config = config
    _join_info = join_info
    _pk_field = pk_field

    db_dep = Depends(get_db)
    user_dep = Depends(_config.login_dep) if _config.login_dep else None

    async def _handler(
        request: Request,
        body: BaseModel,  # annotation patched below to _update_schema
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
    ) -> Any:
        # 1. Route-level auth / permission check
        if _config.login_required and current_user is None:
            raise HTTPException(status_code=401, detail="Authentication required.")
        if _config.permissions and _config.permission_checker is not None:
            if not _config.permission_checker(current_user, _config.permissions):
                raise HTTPException(status_code=403, detail="Insufficient permissions.")

        # 2. Fetch existing object
        pk_value = request.path_params.get("id")
        if pk_value is None:
            raise HTTPException(status_code=400, detail="Missing path param 'id'.")

        pk_col = getattr(_model, _pk_field)
        query = select(_model).where(pk_col == pk_value)

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
            _config.permissions,
            _config.permission_checker,
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
            if asyncio.iscoroutinefunction(setter):
                value = await setter(obj, request, current_user)
            else:
                value = setter(obj, request, current_user)
            patch_data[field_name] = value

        # 8. before_update hook — receives the existing obj and the full patch dict
        if _config.before_update is not None:
            if asyncio.iscoroutinefunction(_config.before_update):
                patch_data = await _config.before_update(obj, patch_data, request, current_user)
            else:
                patch_data = _config.before_update(obj, patch_data, request, current_user)

        # 9. Apply patch to ORM object
        for attr, value in patch_data.items():
            setattr(obj, attr, value)

        # 10. Persist
        db.add(obj)
        await db.commit()

        # 11. Reload with eager-loaded relationships from read_schema
        reload_q = select(_model).where(pk_col == pk_value)
        reload_options = _join_info.eager_load_options(_model, set())
        if reload_options:
            reload_q = reload_q.options(*reload_options)
        result = await db.execute(reload_q)
        obj = result.scalars().unique().one()

        # 12. after_update hook
        if _config.after_update is not None:
            if asyncio.iscoroutinefunction(_config.after_update):
                obj = await _config.after_update(obj, request, current_user)
            else:
                obj = _config.after_update(obj, request, current_user)

        return _read_schema.model_validate(obj, from_attributes=True)

    _handler.__annotations__["body"] = _update_schema

    router.add_api_route(
        path,
        _handler,
        methods=["PATCH"],
        response_model=_read_schema,
        status_code=200,
        tags=_config.tags or None,
        summary=_config.summary,
        dependencies=list(_config.dependencies),
    )
