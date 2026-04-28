from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect, or_
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select


def check_route_permissions(
    current_user: Any,
    login_required: bool,
) -> None:
    """Login check. Raises 401 when login_required and no user is present."""
    if login_required and current_user is None:
        raise HTTPException(status_code=401, detail="Authentication required.")


def check_object_permissions(
    obj: Any,
    model: type[DeclarativeBase],
    current_user: Any,
    login_required: bool,
) -> None:
    """Object-level permission check for read endpoints. Raises 401/403 on failure."""
    check_route_permissions(current_user, login_required)

    if current_user is None:
        return

    checks = _build_object_level_checks(model, current_user)
    if checks and not any(check(obj) for check in checks):
        raise HTTPException(status_code=403, detail="Insufficient permissions.")


def apply_permissions(
    query: Select,
    model: type[DeclarativeBase],
    current_user: Any,
    login_required: bool,
) -> Select:
    check_route_permissions(current_user, login_required)

    if current_user is None:
        return query

    conditions = _build_row_level_conditions(model, current_user)
    if conditions:
        query = query.where(or_(*conditions))

    return query


def _build_object_level_checks(
    model: type[DeclarativeBase],
    current_user: Any,
) -> list[Callable[[Any], bool]]:
    checks: list[Callable[[Any], bool]] = []

    if hasattr(model, "company_id") and hasattr(current_user, "company_id"):
        company_id = current_user.company_id
        checks.append(lambda obj, _t=company_id: obj.company_id == _t)

    if has_allowed_users_relationship(model):
        user_id = getattr(current_user, "id", None)
        if user_id is not None:
            checks.append(
                lambda obj, _uid=user_id: any(u.id == _uid for u in getattr(obj, "allowed_users", []))
            )

    return checks


def _build_row_level_conditions(
    model: type[DeclarativeBase],
    current_user: Any,
) -> list[Any]:
    conditions = []

    if hasattr(model, "company_id") and hasattr(current_user, "company_id"):
        conditions.append(model.company_id == current_user.company_id)

    if has_allowed_users_relationship(model):
        user_id = getattr(current_user, "id", None)
        if user_id is not None:
            user_model = _get_allowed_users_target(model)
            if user_model is not None:
                conditions.append(
                    model.allowed_users.any(user_model.id == user_id)
                )

    return conditions


def has_allowed_users_relationship(model: type[DeclarativeBase]) -> bool:
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
