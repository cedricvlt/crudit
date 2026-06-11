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
from crudit.create.config import CreateConfig
from crudit.exceptions import CruditNotFound, CruditValidationError
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
from crudit.utils import call_hook


def fk_skip_cols_for_create(
    config: CreateConfig, path_filters: dict[str, str]
) -> frozenset[str]:
    """FK columns whose existence is either already validated upstream
    (parent_params do a 404 + permission check; path_filters copy a URL value)
    or set from a trusted source (auto-filled from current_user.id)."""
    return frozenset(
        {pp.child_field for pp in config.parent_params}
        | set(path_filters.values())
        | {"created_by_id", "updated_by_id"}
    )


async def create_service(
    db: AsyncSession,
    ctx: CruditContext,
    *,
    model: type[DeclarativeBase],
    body: BaseModel,
    read_schema: type[BaseModel],
    config: CreateConfig,
    path_filters: dict[str, str] | None = None,
    join_info: JoinInfo | None = None,
    pk_field: str | None = None,
    unique_specs: Any = None,
    fk_specs: Any = None,
) -> BaseModel:
    """Create a row from a validated body and return it serialised as `read_schema`.

    Parent FKs (``config.parent_params``) and path-filter fields are resolved
    from ``ctx.path_params``. Hooks keep their ``(obj, request, user)`` signature
    and receive ``ctx.request`` or a shim when running outside HTTP.

    Raises:
        CruditNotFound: when a parent row does not exist.
        CruditValidationError: when a required path parameter is missing.
        HTTPException: on permission failures and integrity errors (unchanged
            structured details, shared with the HTTP endpoint).
    """
    if join_info is None:
        join_info = resolve_joins(model, read_schema)
    if pk_field is None:
        pk_field = detect_pk_field(model)
    _path_filters = path_filters or {}
    if unique_specs is None:
        unique_specs = detect_unique_constraints(model)
    if fk_specs is None:
        fk_specs = detect_foreign_keys(model)
    fk_skip_cols = fk_skip_cols_for_create(config, _path_filters)

    # 1. Login check
    check_route_permissions(ctx.user, config.login_required)

    # 2. Resolve parents: existence check + row-level permission on each parent
    parent_values: dict[str, Any] = {}
    for pp in config.parent_params:
        url_value = ctx.path_params.get(pp.url_param)
        if url_value is None:
            raise CruditValidationError(f"Missing path parameter '{pp.url_param}'.")
        parent_pk = detect_pk_field(pp.model)
        pk_col = getattr(pp.model, parent_pk)
        pk_python_type = sa_inspect(pp.model).columns[parent_pk].type.python_type
        url_value = pk_python_type(url_value)
        q = select(pp.model).where(pk_col == url_value)
        if has_allowed_users_relationship(pp.model):
            q = q.options(selectinload(getattr(pp.model, "allowed_users")))
        result = await db.execute(q)
        parent = result.scalars().unique().one_or_none()
        if parent is None:
            raise CruditNotFound(f"{pp.model.__name__} with id {url_value!r} not found.")
        check_object_permissions(
            parent,
            pp.model,
            ctx.user,
            config.login_required,
        )
        parent_values[pp.child_field] = url_value

    # 3. Build ORM object from validated body
    obj = model(**body.model_dump())

    # 4. Set parent FK fields (override anything in body)
    for child_field, value in parent_values.items():
        setattr(obj, child_field, value)

    # 4b. Apply path_filters: copy URL value onto the mapped model field
    for url_param, model_field in _path_filters.items():
        url_value = ctx.path_params.get(url_param)
        if url_value is None:
            raise CruditValidationError(f"Missing path parameter '{url_param}'.")
        col_python_type = sa_inspect(model).columns[model_field].type.python_type
        setattr(obj, model_field, col_python_type(url_value))

    # 5. Auto-fill created_at when the column has no server_default
    mapper = sa_inspect(model)
    if "created_at" in mapper.columns:
        col = mapper.columns["created_at"]
        if getattr(col, "server_default", None) is None:
            obj.created_at = datetime.now(timezone.utc)

    # 6. Auto-fill created_by from ctx.user.id
    if "created_by_id" in mapper.columns and ctx.user is not None:
        user_id = getattr(ctx.user, "id", None)
        if user_id is not None:
            obj.created_by_id = user_id

    # 7. Field setters (can be async)
    request = hook_request(ctx)
    for field_name, setter in config.field_setters.items():
        setattr(obj, field_name, await call_hook(setter, obj, request, ctx.user))

    # 8. before_create hook
    if config.before_create is not None:
        obj = await call_hook(config.before_create, obj, request, ctx.user)

    # 9. Pre-flight foreign-key existence check on client-provided body FKs.
    # Uses body.model_dump() (not vars(obj)) so the "only body FKs" scope
    # is a hard contract independent of hook behavior.
    if fk_specs:
        await check_foreign_keys(
            db, fk_specs, body.model_dump(), skip_cols=fk_skip_cols,
        )

    # 10. Pre-flight unique constraint check
    if unique_specs:
        await check_unique_constraints(db, model, unique_specs, vars(obj))

    # 11. Persist
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

    # 12. Reload with eager-loaded relationships from read_schema.
    # `populate_existing` forces relationship attrs to be refreshed on
    # the identity-mapped instance — otherwise setting only `*_by_id`
    # leaves the matching `*_by` relationship unloaded (None) in the
    # response when the session uses expire_on_commit=False.
    pk_col = getattr(model, pk_field)
    pk_value = getattr(obj, pk_field)
    reload_q = select(model).where(pk_col == pk_value).execution_options(populate_existing=True)
    options = join_info.eager_load_options(model, set())
    if options:
        reload_q = reload_q.options(*options)
    result = await db.execute(reload_q)
    obj = result.scalars().unique().one()

    # 13. after_create hook
    if config.after_create is not None:
        obj = await call_hook(config.after_create, obj, request, ctx.user)

    return read_schema.model_validate(obj, from_attributes=True)
