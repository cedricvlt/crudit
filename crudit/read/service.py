from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, selectinload

from crudit.context import CruditContext
from crudit.exceptions import CruditConfigError, CruditNotFound
from crudit.joins import JoinInfo, resolve_joins
from crudit.permissions import check_object_permissions, has_allowed_users_relationship
from crudit.read.config import ReadConfig
from crudit.utils import call_hook


def detect_pk_field(model: type[DeclarativeBase]) -> str:
    """Return the single primary-key column name for `model`.

    Raises CruditConfigError when the model has zero or multiple PK columns.
    """
    mapper = sa_inspect(model)
    pk_cols = list(mapper.primary_key)
    if len(pk_cols) != 1:
        raise CruditConfigError(
            f"{model.__name__} must have exactly one primary key column for read_endpoint."
        )
    return pk_cols[0].name


async def read_service(
    db: AsyncSession,
    ctx: CruditContext,
    *,
    model: type[DeclarativeBase],
    schema: type[BaseModel],
    config: ReadConfig,
    id: Any,
    join_info: JoinInfo | None = None,
    pk_field: str | None = None,
) -> BaseModel:
    """Fetch a single object by primary key and return it serialised.

    Raises:
        CruditNotFound: when no row matches `id`.
        CruditForbidden / HTTPException(401|403): on permission failures
            (via `check_object_permissions`).
    """
    if join_info is None:
        join_info = resolve_joins(model, schema)
    if pk_field is None:
        pk_field = detect_pk_field(model)

    load_allowed_users = (
        has_allowed_users_relationship(model)
        and "allowed_users" not in join_info.nodes
    )

    pk_col = getattr(model, pk_field)
    query = select(model).where(pk_col == id)

    options = join_info.eager_load_options(model, set())
    if load_allowed_users:
        options.append(selectinload(getattr(model, "allowed_users")))
    if options:
        query = query.options(*options)

    if config.before_query is not None:
        query = await call_hook(config.before_query, query, ctx)

    computed_names = list(config.computed_fields.keys())
    if computed_names:
        query = query.add_columns(
            *[fn(model).label(name) for name, fn in config.computed_fields.items()]
        )

    result = await db.execute(query)
    if computed_names:
        row = result.unique().one_or_none()
        if row is None:
            obj = None
        else:
            obj = row[0]
            for i, name in enumerate(computed_names, start=1):
                setattr(obj, name, row[i])
    else:
        obj = result.scalars().unique().one_or_none()

    if obj is None:
        raise CruditNotFound(f"{model.__name__} with id {id!r} not found.")

    check_object_permissions(obj, model, ctx.user, config.login_required)

    if config.after_query is not None:
        obj = await call_hook(config.after_query, obj, ctx)

    return schema.model_validate(obj, from_attributes=True)
