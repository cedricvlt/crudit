from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect, or_
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select

from crudite.types import PermissionChecker


def apply_permissions(
    query: Select,
    model: type[DeclarativeBase],
    current_user: Any,
    login_required: bool,
    permissions: list[str],
    permission_checker: PermissionChecker | None,
) -> Select:
    if login_required and current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if current_user is None:
        return query

    if permissions and permission_checker is not None:
        if not permission_checker(current_user, permissions):
            raise HTTPException(status_code=403, detail="Insufficient permissions.")

    conditions = _build_row_level_conditions(model, current_user)
    if conditions:
        query = query.where(or_(*conditions))

    return query


def _build_row_level_conditions(
    model: type[DeclarativeBase],
    current_user: Any,
) -> list[Any]:
    conditions = []

    if hasattr(model, "tenant_id") and hasattr(current_user, "tenant_id"):
        conditions.append(model.tenant_id == current_user.tenant_id)

    if _has_allowed_users_relationship(model):
        user_id = getattr(current_user, "id", None)
        if user_id is not None:
            user_model = _get_allowed_users_target(model)
            if user_model is not None:
                conditions.append(
                    model.allowed_users.any(user_model.id == user_id)
                )

    return conditions


def _has_allowed_users_relationship(model: type[DeclarativeBase]) -> bool:
    try:
        mapper = sa_inspect(model)
        return "allowed_users" in {r.key for r in mapper.relationships}
    except Exception:
        return False


def _get_allowed_users_target(model: type[DeclarativeBase]) -> type | None:
    try:
        mapper = sa_inspect(model)
        for rel in mapper.relationships:
            if rel.key == "allowed_users":
                return rel.mapper.class_
        return None
    except Exception:
        return None
