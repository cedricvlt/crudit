from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect, or_
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select

from crudite.types import PermissionChecker


def check_object_permissions(
    obj: Any,
    model: type[DeclarativeBase],
    current_user: Any,
    login_required: bool,
    permissions: list[str],
    permission_checker: PermissionChecker | None,
) -> None:
    """Object-level permission check for read endpoints. Raises 401/403 on failure."""
    if login_required and current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if current_user is None:
        return

    if permissions and permission_checker is not None:
        if not permission_checker(current_user, permissions):
            raise HTTPException(status_code=403, detail="Insufficient permissions.")

    # Row-level: mirrors the SQL or_(*conditions) from apply_permissions
    checks = _build_object_level_checks(model, current_user)
    if checks and not any(check(obj) for check in checks):
        raise HTTPException(status_code=403, detail="Insufficient permissions.")


def _build_object_level_checks(
    model: type[DeclarativeBase],
    current_user: Any,
) -> list[Callable[[Any], bool]]:
    checks: list[Callable[[Any], bool]] = []

    if hasattr(model, "tenant_id") and hasattr(current_user, "tenant_id"):
        tenant_id = current_user.tenant_id
        checks.append(lambda obj, _t=tenant_id: obj.tenant_id == _t)

    if _has_allowed_users_relationship(model):
        user_id = getattr(current_user, "id", None)
        if user_id is not None:
            checks.append(
                lambda obj, _uid=user_id: any(u.id == _uid for u in getattr(obj, "allowed_users", []))
            )

    return checks


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
