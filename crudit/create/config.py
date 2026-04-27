from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import DeclarativeBase

from crudit.types import CreateHookFn, FieldSetterFn


@dataclass
class ParentParam:
    url_param: str               # path param name, e.g. "city_id"
    model: type[DeclarativeBase]  # parent SQLAlchemy model
    child_field: str             # FK field on child to set, e.g. "city_id"


@dataclass
class CreateConfig:
    # Parent resolution: each entry fetches the parent, checks 404 + permissions,
    # and sets the FK on the child.
    parent_params: list[ParentParam] = field(default_factory=list)

    # Field setters: field_name → callable(obj, request, current_user) → value.
    # Called after auto-complete; can be async.
    field_setters: dict[str, FieldSetterFn] = field(default_factory=dict)

    # Permissions
    permissions: list[str] = field(default_factory=list)
    login_required: bool = True

    # Hooks
    before_create: CreateHookFn | None = None
    after_create: CreateHookFn | None = None

    # FastAPI
    dependencies: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
