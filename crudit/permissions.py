from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException
from sqlalchemy import inspect as sa_inspect, or_, select
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql import Select

from crudit.exceptions import CruditConfigError, CruditNotFound


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
        target = _companies_target_table(current_user)
        if target is None or not _company_fk_conflicts(model, target):
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

    if not _is_directly_scoped(model):
        via = _scope_via_condition(model, current_user)
        return [via] if via is not None else []

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


# --- Child scoping (``_scope_via``) -------------------------------------------
#
# A child row (an order line, a payment, a report…) carries no ``company_id`` of
# its own: it belongs to whoever may see its parent. A model opts in by naming
# the many-to-one relationship to that parent, like ``_order_fields``:
#
#     class OrderLine(Base):
#         _scope_via = "sale"
#
# The row is then visible iff its parent is, under the parent's own rules
# (company, allowed_users, or the parent's own ``_scope_via`` — chains such as
# room → floor → building → expertise resolve recursively). Being a model
# attribute, it applies to every caller of ``apply_permissions``: list, options,
# m2m, the by-id fetches below, and non-HTTP callers going through the services.


def _is_directly_scoped(model: type[DeclarativeBase]) -> bool:
    return hasattr(model, "company_id") or has_allowed_users_relationship(model)


def _scope_via_relationship(model: type[DeclarativeBase]) -> Any | None:
    name = getattr(model, "_scope_via", None)
    if not name:
        return None
    try:
        rel = sa_inspect(model).relationships[name]
    except KeyError:
        raise CruditConfigError(
            f"{model.__name__}._scope_via names {name!r}, which is not a relationship."
        ) from None
    if rel.uselist:
        raise CruditConfigError(
            f"{model.__name__}._scope_via must name a many-to-one relationship, "
            f"not the collection {name!r}."
        )
    return rel


def _scope_via_condition(model: type[DeclarativeBase], current_user: Any) -> Any | None:
    """``model.<parent>.has(<parent's row-level conditions>)``, or None when the
    model has no ``_scope_via`` or its parent is not scoped either."""
    rel = _scope_via_relationship(model)
    if rel is None:
        return None
    parent_conditions = _build_row_level_conditions(rel.mapper.class_, current_user)
    if not parent_conditions:
        return None
    return getattr(model, rel.key).has(or_(*parent_conditions))


def apply_scope_via(query: Select, model: type[DeclarativeBase], current_user: Any) -> Select:
    """Narrow a by-id fetch of ``model`` to rows whose parent the user may see.

    Direct rules (company, allowed_users) keep their object-level 403 check; a
    child out of reach through its parent is simply not found.
    """
    if current_user is None or _is_directly_scoped(model):
        return query
    condition = _scope_via_condition(model, current_user)
    return query.where(condition) if condition is not None else query


def is_scoped(model: type[DeclarativeBase]) -> bool:
    """Whether any row-level rule can hide rows of ``model``."""
    return _is_directly_scoped(model) or getattr(model, "_scope_via", None) is not None


def _parent_model_for(model: type[DeclarativeBase], field: str) -> type | None:
    """The model a local FK column points at, through its many-to-one relationship."""
    column = sa_inspect(model).columns.get(field)
    if column is None:
        return None
    for rel in sa_inspect(model).relationships:
        if not rel.uselist and column in rel.local_columns:
            return rel.mapper.class_
    return None


async def ensure_path_parents_visible(
    db: Any,
    model: type[DeclarativeBase],
    path_filters: dict[str, str],
    path_params: dict[str, Any],
    current_user: Any,
) -> None:
    """404 when a nested route's parent (``/sales/{sale_id}/order-lines``) is out
    of the user's reach — on every verb, list included, so a parent id from
    another company neither lists its children nor receives new ones."""
    if current_user is None:
        return
    for param, field in path_filters.items():
        parent = _parent_model_for(model, field)
        raw = path_params.get(param)
        if parent is None or raw is None or not is_scoped(parent):
            continue
        pk = list(sa_inspect(parent).primary_key)[0]
        value = pk.type.python_type(raw) if isinstance(raw, str) else raw
        query = apply_permissions(
            select(pk).where(pk == value), parent, current_user, login_required=False
        )
        if (await db.execute(query)).first() is None:
            raise CruditNotFound(f"{parent.__name__} with id {raw!r} not found.")


def check_company_assignment(
    model: type[DeclarativeBase], values: dict[str, Any], current_user: Any
) -> None:
    """A row may only be written into one of the user's companies.

    Superusers are exempt (they administer every company). Raises the same 422
    as an unknown foreign key, so a foreign company's existence is not leaked.
    """
    if current_user is None or getattr(current_user, "is_superuser", False):
        return
    if "company_id" not in values or values["company_id"] is None:
        return
    if _company_scope_condition(model, current_user) is None:
        return
    allowed = {c.id for c in current_user.companies}
    if values["company_id"] not in allowed:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "Validation failed",
                "fields": {"company_id": ["Does not exist"]},
            },
        )


def _company_scope_condition(
    model: type[DeclarativeBase],
    current_user: Any,
) -> Any | None:
    """SQL condition scoping ``model`` rows to the current user's companies.

    Returns ``None`` when the model has no ``company_id`` (nothing to scope), when
    the user has no ``companies`` relationship, or when ``model.company_id`` is
    demonstrably a foreign key to some table other than the one ``companies``
    points at — see ``_company_fk_conflicts``.

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

    target = _companies_target_table(current_user)
    if target is not None and _company_fk_conflicts(model, target):
        return None

    return model.company_id.in_([c.id for c in current_user.companies])


def _companies_target_table(current_user: Any) -> Any | None:
    """Table that ``current_user.companies`` targets, or ``None`` if undeterminable.

    ``None`` means "could not prove anything" (e.g. the user object is not a mapped
    class, or exposes ``companies`` as a plain attribute), never "no scoping".
    """
    try:
        mapper = sa_inspect(type(current_user))
        for rel in mapper.relationships:
            if rel.key == "companies":
                return rel.target
        return None
    except Exception:
        return None


def _company_fk_conflicts(model: type[DeclarativeBase], target_table: Any) -> bool:
    """True when ``model.company_id`` provably foreign-keys a *different* table.

    ``company_id`` is scoping's only signal, so a model that reuses the name for an
    unrelated foreign key (say, a link row pointing at a *contact* that happens to be
    a company) would otherwise be silently filtered down to zero rows.

    Deliberately conservative: a column with no foreign keys at all proves nothing,
    so it stays scoped. Only a column whose every foreign key points somewhere other
    than ``target_table`` is treated as a conflict.
    """
    try:
        columns = model.company_id.property.columns
    except AttributeError:
        return False

    foreign_keys = [fk for column in columns for fk in column.foreign_keys]
    if not foreign_keys:
        return False

    return all(fk.column.table is not target_table for fk in foreign_keys)


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
