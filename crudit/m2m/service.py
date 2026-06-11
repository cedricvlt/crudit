from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy import Column, Table, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from crudit.context import CruditContext
from crudit.exceptions import CruditNotFound, CruditValidationError
from crudit.joins import JoinInfo
from crudit.m2m.config import M2MConfig
from crudit.permissions import (
    check_object_permissions,
    check_route_permissions,
    has_allowed_users_relationship,
)
from crudit.read.service import detect_pk_field
from crudit.utils import call_hook


@dataclass
class M2MSpec:
    """Registration-time resolution of one M2M relationship, shared by the
    HTTP endpoints and non-HTTP callers (MCP tools)."""

    parent_model: type
    child_model: type
    association_table: Table
    child_schema: type[BaseModel]
    parent_fk_col: Column
    child_fk_col: Column
    join_info: JoinInfo
    config: M2MConfig
    # Whether login is actually enforced for this relationship. Mirrors the
    # router behaviour: ``config.login_required`` only takes effect when a
    # ``login_dep`` was wired at registration time.
    login_enforced: bool = True


async def get_parent_or_not_found(
    db: AsyncSession, ctx: CruditContext, spec: M2MSpec, parent_id: int
):
    """Fetch the parent row, raising CruditNotFound when absent, and apply
    row-level permission checks (company scoping / allowed_users)."""
    pk_field = detect_pk_field(spec.parent_model)
    query = select(spec.parent_model).where(
        getattr(spec.parent_model, pk_field) == parent_id
    )
    if has_allowed_users_relationship(spec.parent_model):
        query = query.options(selectinload(getattr(spec.parent_model, "allowed_users")))
    result = await db.execute(query)
    parent = result.scalars().unique().one_or_none()
    if parent is None:
        raise CruditNotFound(
            f"{spec.parent_model.__name__} with id {parent_id!r} not found."
        )
    check_object_permissions(
        parent,
        spec.parent_model,
        ctx.user,
        spec.login_enforced,
    )
    return parent


async def _list_children(db: AsyncSession, spec: M2MSpec, parent_id: int) -> list[BaseModel]:
    query = (
        select(spec.child_model)
        .join(spec.association_table, spec.child_model.id == spec.child_fk_col)
        .where(spec.parent_fk_col == parent_id)
    )
    options = spec.join_info.eager_load_options(spec.child_model, set())
    if options:
        query = query.options(*options)
    rows = (await db.scalars(query)).unique().all()
    spec.join_info.sort_o2m_collections(list(rows))
    return [
        spec.child_schema.model_validate(row, from_attributes=True) for row in rows
    ]


async def m2m_list_service(
    db: AsyncSession,
    ctx: CruditContext,
    *,
    spec: M2MSpec,
    parent_id: int,
) -> list[BaseModel]:
    """List linked children, serialised as the child schema.

    Raises CruditNotFound when the parent does not exist; HTTPException(403)
    when the parent fails row-level checks.
    """
    check_route_permissions(ctx.user, spec.login_enforced)
    await get_parent_or_not_found(db, ctx, spec, parent_id)
    return await _list_children(db, spec, parent_id)


async def m2m_add_service(
    db: AsyncSession,
    ctx: CruditContext,
    *,
    spec: M2MSpec,
    parent_id: int,
    child_ids: list[int],
) -> list[BaseModel]:
    """Link children to the parent (idempotent) and return the updated list.

    Raises:
        CruditNotFound: when the parent does not exist.
        CruditValidationError: when some child ids do not exist
            (``fields={"ids": [...]}``).
    """
    check_route_permissions(ctx.user, spec.login_enforced)
    await get_parent_or_not_found(db, ctx, spec, parent_id)

    if child_ids:
        existing = set(
            (
                await db.scalars(
                    select(spec.child_model.id).where(spec.child_model.id.in_(child_ids))
                )
            ).all()
        )
        missing = set(child_ids) - existing
        if missing:
            raise CruditValidationError(
                f"IDs not found: {sorted(missing)}",
                fields={"ids": [f"IDs not found: {sorted(missing)}"]},
            )

        already_linked = set(
            (
                await db.scalars(
                    select(spec.child_fk_col).where(
                        spec.parent_fk_col == parent_id,
                        spec.child_fk_col.in_(child_ids),
                    )
                )
            ).all()
        )
        new_ids = [cid for cid in child_ids if cid not in already_linked]
        if new_ids:
            await db.execute(
                spec.association_table.insert().values(
                    [
                        {spec.parent_fk_col.name: parent_id, spec.child_fk_col.name: cid}
                        for cid in new_ids
                    ]
                )
            )
            if spec.config.after_add is not None:
                await call_hook(spec.config.after_add, parent_id, new_ids, db, ctx.user)
        await db.commit()

    return await _list_children(db, spec, parent_id)


async def m2m_remove_service(
    db: AsyncSession,
    ctx: CruditContext,
    *,
    spec: M2MSpec,
    parent_id: int,
    child_ids: list[int],
) -> None:
    """Unlink children from the parent (idempotent).

    Raises CruditNotFound when the parent does not exist.
    """
    check_route_permissions(ctx.user, spec.login_enforced)
    await get_parent_or_not_found(db, ctx, spec, parent_id)

    if child_ids:
        await db.execute(
            delete(spec.association_table).where(
                spec.parent_fk_col == parent_id,
                spec.child_fk_col.in_(child_ids),
            )
        )
        if spec.config.after_remove is not None:
            await call_hook(spec.config.after_remove, parent_id, child_ids, db, ctx.user)
        await db.commit()
