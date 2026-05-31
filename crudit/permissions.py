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

    if hasattr(model, "company_id") and hasattr(current_user, "companies"):
        company_ids = {c.id for c in current_user.companies}
        checks.append(lambda obj, _ids=company_ids: obj.company_id in _ids)

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

    company_condition = _company_scope_condition(model, current_user)
    if company_condition is not None:
        conditions.append(company_condition)

    if has_allowed_users_relationship(model):
        user_id = getattr(current_user, "id", None)
        if user_id is not None:
            user_model = _get_allowed_users_target(model)
            if user_model is not None:
                conditions.append(
                    model.allowed_users.any(user_model.id == user_id)
                )

    return conditions


def _company_scope_condition(
    model: type[DeclarativeBase],
    current_user: Any,
) -> Any | None:
    """SQL condition scoping ``model`` rows to the current user's companies.

    Returns ``None`` when the model has no ``company_id`` (nothing to scope) or
    when the user has no ``companies`` relationship.

    Users are multi-company: ``current_user.companies`` is a many-to-many
    relationship. This emits ``model.company_id IN (<user's company ids>)``.

    The user's ``companies`` collection must be **loaded** before the request
    handler reads it — eager-load it (``lazy="selectin"``) or load it in the auth
    dependency. The handler is async, so a lazy collection would raise
    ``MissingGreenlet`` here. An empty collection yields an ``IN ()`` that matches
    no rows, which is the correct result for a user belonging to no company.
    """
    if not hasattr(model, "company_id") or not hasattr(current_user, "companies"):
        return None

    return model.company_id.in_([c.id for c in current_user.companies])


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
