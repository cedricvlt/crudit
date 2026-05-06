from __future__ import annotations

import inspect
from typing import Any, Callable

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.params import Depends as DependsType
from pydantic import BaseModel
from sqlalchemy import Column, Table, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from crudit.m2m.config import M2MConfig
from crudit.types import PermissionDepFn
from crudit.utils import bind_perms, get_error_responses, model_snake_name


class M2MIdsBody(BaseModel):
    ids: list[int]


def _resolve_association_columns(
    association_table: Table,
    parent_model: type,
    child_model: type,
) -> tuple[Column, Column]:
    parent_table = parent_model.__tablename__
    child_table = child_model.__tablename__
    parent_col = child_col = None
    for col in association_table.columns:
        for fk in col.foreign_keys:
            target_table = fk.column.table.name
            if target_table == parent_table:
                parent_col = col
            elif target_table == child_table:
                child_col = col
    if parent_col is None or child_col is None:
        raise ValueError(
            f"Could not resolve FK columns in {association_table.name} "
            f"for {parent_table} and {child_table}"
        )
    return parent_col, child_col


def m2m_router(
    *,
    parent_model: type,
    child_model: type,
    association_table: Table,
    child_schema: type[BaseModel],
    prefix: str,
    get_db: Callable,
    config: M2MConfig | None = None,
    login_dep: Callable | None = None,
    permission_dep: PermissionDepFn | None = None,
) -> APIRouter:
    """Build an APIRouter with list / add / remove endpoints for a M2M relationship.

    Args:
        parent_model: SQLAlchemy model of the parent side (e.g. User).
        child_model: SQLAlchemy model of the child side (e.g. Permission).
        association_table: SQLAlchemy Table linking both models.
        child_schema: Pydantic schema used to serialize child items in responses.
        prefix: Router prefix, e.g. ``"/users"``.
        get_db: Async session factory dependency.
        config: Optional M2MConfig for tags, dependencies, auth, etc.
        login_dep: FastAPI dependency that resolves the current user.
        permission_dep: Permission dependency factory (same form as in crud_router).
    """
    cfg = config or M2MConfig()

    _login_codes = (401,) if (cfg.login_required and login_dep is not None) else ()

    parent_fk_col, child_fk_col = _resolve_association_columns(
        association_table, parent_model, child_model
    )
    parent_pk_param = parent_fk_col.name
    child_path_segment = cfg.child_path_segment or (child_model.__name__.lower() + "s")
    base_path = f"{prefix}/{{{parent_pk_param}}}/{child_path_segment}"

    router = APIRouter(tags=cfg.tags or [])

    extra_deps: list[Any] = list(cfg.dependencies)
    if cfg.login_required and login_dep is not None:
        extra_deps.append(Depends(login_dep))
    if permission_dep is not None and cfg.permissions:
        extra_deps.append(Depends(bind_perms(permission_dep, cfg.permissions)))

    resolved_deps = [Depends(d) if not isinstance(d, DependsType) else d for d in extra_deps]
    model_name = f"{parent_model.__name__}{child_model.__name__}"
    op_id_base = f"{model_snake_name(parent_model)}_{model_snake_name(child_model)}"
    list_op_id = cfg.list_operation_id or f"list_{op_id_base}"
    add_op_id = cfg.add_operation_id or f"add_{op_id_base}"
    remove_op_id = cfg.remove_operation_id or f"remove_{op_id_base}"

    db_dep = Depends(get_db)

    # -- helpers --

    async def _get_parent_or_404(db: AsyncSession, parent_id: int) -> None:
        parent = await db.get(parent_model, parent_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Not found.")

    async def _list_children(db: AsyncSession, parent_id: int) -> list[BaseModel]:
        rows = (
            await db.scalars(
                select(child_model)
                .join(association_table, child_model.id == child_fk_col)
                .where(parent_fk_col == parent_id)
            )
        ).all()
        return [child_schema.model_validate(row, from_attributes=True) for row in rows]

    # -- endpoints --

    async def list_endpoint(
        db: AsyncSession = db_dep,
        **path_params: int,
    ) -> list[child_schema]:  # type: ignore[valid-type]
        parent_id = path_params[parent_pk_param]
        await _get_parent_or_404(db, parent_id)
        return await _list_children(db, parent_id)

    async def add_endpoint(
        body: M2MIdsBody = Body(...),
        db: AsyncSession = db_dep,
        **path_params: int,
    ) -> list[child_schema]:  # type: ignore[valid-type]
        parent_id = path_params[parent_pk_param]
        await _get_parent_or_404(db, parent_id)

        if body.ids:
            existing = set(
                (
                    await db.scalars(
                        select(child_model.id).where(child_model.id.in_(body.ids))
                    )
                ).all()
            )
            missing = set(body.ids) - existing
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail={"ids": [f"IDs not found: {sorted(missing)}"]},
                )

            already_linked = set(
                (
                    await db.scalars(
                        select(child_fk_col).where(
                            parent_fk_col == parent_id,
                            child_fk_col.in_(body.ids),
                        )
                    )
                ).all()
            )
            new_ids = [cid for cid in body.ids if cid not in already_linked]
            if new_ids:
                await db.execute(
                    association_table.insert().values(
                        [{parent_fk_col.name: parent_id, child_fk_col.name: cid} for cid in new_ids]
                    )
                )
            await db.commit()

        return await _list_children(db, parent_id)

    async def remove_endpoint(
        body: M2MIdsBody = Body(...),
        db: AsyncSession = db_dep,
        **path_params: int,
    ) -> None:
        parent_id = path_params[parent_pk_param]
        await _get_parent_or_404(db, parent_id)

        if body.ids:
            await db.execute(
                delete(association_table).where(
                    parent_fk_col == parent_id,
                    child_fk_col.in_(body.ids),
                )
            )
            await db.commit()

    # -- inject path parameter into signatures --

    for fn in (list_endpoint, add_endpoint, remove_endpoint):
        sig = inspect.signature(fn)
        params = [p for p in sig.parameters.values() if p.kind != inspect.Parameter.VAR_KEYWORD]
        params.append(
            inspect.Parameter(
                parent_pk_param,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=int,
            )
        )
        fn.__signature__ = sig.replace(parameters=params)  # type: ignore[attr-defined]

    # -- register routes --

    router.add_api_route(
        base_path,
        list_endpoint,
        methods=["GET"],
        response_model=list[child_schema],
        dependencies=resolved_deps,
        responses=get_error_responses(*_login_codes, 403, 404),
        name=f"{model_name.lower()}_m2m_list",
        operation_id=list_op_id,
        description=f"List {child_model.__name__} items linked to a {parent_model.__name__}.",
    )

    router.add_api_route(
        base_path,
        add_endpoint,
        methods=["POST"],
        response_model=list[child_schema],
        dependencies=resolved_deps,
        responses=get_error_responses(*_login_codes, 403, 404, 422),
        name=f"{model_name.lower()}_m2m_add",
        operation_id=add_op_id,
        description=f"Add {child_model.__name__} items to a {parent_model.__name__}. Idempotent.",
    )

    router.add_api_route(
        base_path,
        remove_endpoint,
        methods=["DELETE"],
        status_code=204,
        dependencies=resolved_deps,
        responses=get_error_responses(*_login_codes, 403, 404),
        name=f"{model_name.lower()}_m2m_remove",
        operation_id=remove_op_id,
        description=f"Remove {child_model.__name__} items from a {parent_model.__name__}. Idempotent.",
    )

    return router