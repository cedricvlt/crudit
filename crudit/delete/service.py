from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, selectinload

from crudit.context import CruditContext, hook_request
from crudit.delete.config import DeleteConfig
from crudit.exceptions import CruditNotFound
from crudit.permissions import (
    check_object_permissions,
    check_route_permissions,
    has_allowed_users_relationship,
)
from crudit.read.service import detect_pk_field
from crudit.utils import call_hook


async def delete_service(
    db: AsyncSession,
    ctx: CruditContext,
    *,
    model: type[DeclarativeBase],
    config: DeleteConfig,
    id: Any,
    pk_field: str | None = None,
) -> None:
    """Delete a row after row-level permission checks.

    Raises:
        CruditNotFound: when no row matches `id`.
        HTTPException: on permission failures, or 409 when the row is still
            referenced by other rows (FK RESTRICT).
    """
    if pk_field is None:
        pk_field = detect_pk_field(model)

    # 1. Login check
    check_route_permissions(ctx.user, config.login_required)

    # 2. Fetch object
    pk_col = getattr(model, pk_field)
    query = select(model).where(pk_col == id)

    if has_allowed_users_relationship(model):
        query = query.options(selectinload(getattr(model, "allowed_users")))

    result = await db.execute(query)
    obj = result.scalars().unique().one_or_none()

    if obj is None:
        raise CruditNotFound(f"{model.__name__} with id {id!r} not found.")

    # 3. Object-level permission check
    check_object_permissions(
        obj,
        model,
        ctx.user,
        config.login_required,
    )

    # 4. before_delete hook — can raise to abort
    request = hook_request(ctx)
    if config.before_delete is not None:
        await call_hook(config.before_delete, obj, request, ctx.user)

    # 5. Delete and commit
    await db.delete(obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DELETE_CONFLICT",
                "message": (
                    f"{model.__name__} {id!r} is still referenced by other "
                    "rows and cannot be deleted."
                ),
            },
        )

    # 6. after_delete hook — obj is detached but attributes are still accessible
    if config.after_delete is not None:
        await call_hook(config.after_delete, obj, request, ctx.user)
