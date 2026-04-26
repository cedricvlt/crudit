from __future__ import annotations

import asyncio
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, selectinload

from crudit.delete.config import DeleteConfig
from crudit.permissions import check_object_permissions, has_allowed_users_relationship
from crudit.read.endpoint import _detect_pk_field


def delete_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    config: DeleteConfig,
    *,
    get_db: Callable,
) -> None:
    """
    Register a DELETE endpoint that removes an existing object and returns 204 No Content.

    Row-level permission checks (tenant_id / allowed_users) are applied before deletion.
    """
    pk_field = _detect_pk_field(model)
    load_allowed_users = has_allowed_users_relationship(model)

    _model = model
    _config = config
    _pk_field = pk_field

    db_dep = Depends(get_db)
    user_dep = Depends(_config.login_dep) if _config.login_dep else None

    async def _handler(
        request: Request,
        db: AsyncSession = db_dep,
        current_user: Any = user_dep,
    ) -> Response:
        # 1. Route-level auth / permission check
        if _config.login_required and current_user is None:
            raise HTTPException(status_code=401, detail="Authentication required.")
        if _config.permissions and _config.permission_checker is not None:
            if not _config.permission_checker(current_user, _config.permissions):
                raise HTTPException(status_code=403, detail="Insufficient permissions.")

        # 2. Fetch object
        pk_value = request.path_params.get("id")
        if pk_value is None:
            raise HTTPException(status_code=400, detail="Missing path param 'id'.")

        pk_col = getattr(_model, _pk_field)
        query = select(_model).where(pk_col == pk_value)

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
            _config.permissions,
            _config.permission_checker,
        )

        # 4. before_delete hook — can raise to abort
        if _config.before_delete is not None:
            if asyncio.iscoroutinefunction(_config.before_delete):
                await _config.before_delete(obj, request, current_user)
            else:
                _config.before_delete(obj, request, current_user)

        # 5. Delete and commit
        await db.delete(obj)
        await db.commit()

        # 6. after_delete hook — obj is detached but attributes are still accessible
        if _config.after_delete is not None:
            if asyncio.iscoroutinefunction(_config.after_delete):
                await _config.after_delete(obj, request, current_user)
            else:
                _config.after_delete(obj, request, current_user)

        return Response(status_code=204)

    router.add_api_route(
        path,
        _handler,
        methods=["DELETE"],
        status_code=204,
        response_class=Response,
        tags=_config.tags or None,
        summary=_config.summary,
        dependencies=list(_config.dependencies),
    )
