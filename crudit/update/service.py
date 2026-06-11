from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, selectinload

from crudit.context import CruditContext, hook_request
from crudit.exceptions import CruditNotFound
from crudit.foreign_keys import (
    check_foreign_keys,
    detect_foreign_keys,
    integrity_error_to_http as fk_integrity_error_to_http,
)
from crudit.joins import JoinInfo, resolve_joins
from crudit.permissions import (
    check_object_permissions,
    check_route_permissions,
    has_allowed_users_relationship,
)
from crudit.read.service import detect_pk_field
from crudit.unique_constraints import (
    check_unique_constraints,
    detect_unique_constraints,
    integrity_error_to_http,
)
from crudit.update.config import UpdateConfig
from crudit.utils import call_hook

# updated_by_id is auto-filled from the current user's id — trusted, skip.
_FK_SKIP_COLS: frozenset[str] = frozenset({"updated_by_id"})


async def update_service(
    db: AsyncSession,
    ctx: CruditContext,
    *,
    model: type[DeclarativeBase],
    body: BaseModel,
    read_schema: type[BaseModel],
    config: UpdateConfig,
    id: Any,
    join_info: JoinInfo | None = None,
    pk_field: str | None = None,
    unique_specs: Any = None,
    fk_specs: Any = None,
) -> BaseModel:
    """Partially update a row and return it serialised as `read_schema`.

    Only fields set on `body` are applied (`model_dump(exclude_unset=True)`),
    so non-HTTP callers must build the body with
    ``update_schema.model_validate(partial_dict)`` to get the same semantics.

    Raises:
        CruditNotFound: when no row matches `id`.
        HTTPException: on permission failures and integrity errors (unchanged
            structured details, shared with the HTTP endpoint).
    """
    if join_info is None:
        join_info = resolve_joins(model, read_schema)
    if pk_field is None:
        pk_field = detect_pk_field(model)
    if unique_specs is None:
        unique_specs = detect_unique_constraints(model)
    if fk_specs is None:
        fk_specs = detect_foreign_keys(model)
    load_allowed_users = (
        has_allowed_users_relationship(model)
        and "allowed_users" not in join_info.nodes
    )

    # 1. Login check
    check_route_permissions(ctx.user, config.login_required)

    # 2. Fetch existing object
    pk_col = getattr(model, pk_field)
    query = select(model).where(pk_col == id)

    options = join_info.eager_load_options(model, set())
    if load_allowed_users:
        options.append(selectinload(getattr(model, "allowed_users")))
    if options:
        query = query.options(*options)

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

    # 4. Build patch dict (only fields the client sent)
    patch_data: dict[str, Any] = body.model_dump(exclude_unset=True)

    # 5. Auto-fill updated_at when the column has no server_default
    mapper = sa_inspect(model)
    if "updated_at" in mapper.columns:
        col = mapper.columns["updated_at"]
        if getattr(col, "server_default", None) is None:
            patch_data["updated_at"] = datetime.now(timezone.utc)

    # 6. Auto-fill updated_by from ctx.user.id
    if "updated_by_id" in mapper.columns and ctx.user is not None:
        user_id = getattr(ctx.user, "id", None)
        if user_id is not None:
            patch_data["updated_by_id"] = user_id

    # 7. Field setters (can be async)
    request = hook_request(ctx)
    for field_name, setter in config.field_setters.items():
        patch_data[field_name] = await call_hook(setter, obj, request, ctx.user)

    # 8. before_update hook — receives the existing obj and the full patch dict
    if config.before_update is not None:
        patch_data = await call_hook(config.before_update, obj, patch_data, request, ctx.user)

    # 9. Pre-flight foreign-key check on client-provided patch fields.
    # patch_data is exclude_unset, so a PATCH that touches no FK column
    # results in zero FK queries. Runs before the unique check so an
    # invalid FK is reported instead of a downstream uniqueness error.
    if fk_specs:
        await check_foreign_keys(
            db, fk_specs, patch_data, skip_cols=_FK_SKIP_COLS,
        )

    # 10. Pre-flight unique constraint check using the post-patch values.
    # We check before mutating `obj` so the SELECT's implicit autoflush
    # doesn't try to push the dirty row into the DB and raise IntegrityError
    # itself.
    if unique_specs:
        values = {c.key: getattr(obj, c.key) for c in mapper.columns}
        values.update(patch_data)
        await check_unique_constraints(
            db, model, unique_specs, values,
            exclude_pk=(pk_field, id),
        )

    # 11. Apply patch to ORM object
    for attr, value in patch_data.items():
        setattr(obj, attr, value)

    # 12. Persist
    db.add(obj)
    try:
        await db.commit()
    except IntegrityError as err:
        await db.rollback()
        raise (
            integrity_error_to_http(err, unique_specs)
            or fk_integrity_error_to_http(err, fk_specs)
            or HTTPException(
                status_code=422,
                detail={"code": "VALIDATION_ERROR", "message": "Validation failed"},
            )
        )

    # 13. Reload with eager-loaded relationships from read_schema.
    # `populate_existing` forces relationship attrs to be refreshed on
    # the identity-mapped instance — otherwise setting only `*_by_id`
    # leaves the matching `*_by` relationship stale (or None) in the
    # response when the session uses expire_on_commit=False.
    reload_q = select(model).where(pk_col == id).execution_options(populate_existing=True)
    reload_options = join_info.eager_load_options(model, set())
    if reload_options:
        reload_q = reload_q.options(*reload_options)
    result = await db.execute(reload_q)
    obj = result.scalars().unique().one()

    # 14. after_update hook
    if config.after_update is not None:
        obj = await call_hook(config.after_update, obj, request, ctx.user)

    return read_schema.model_validate(obj, from_attributes=True)
