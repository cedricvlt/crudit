from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from crudit.types import FieldSetterFn, PermissionDepFn, UpdateAfterHookFn, UpdateBeforeHookFn


@dataclass
class UpdateConfig:
    # Field setters: field_name → callable(obj, request, current_user) → value.
    # Called after auto-complete; can be async.
    field_setters: dict[str, FieldSetterFn] = field(default_factory=dict)

    # Permissions
    permissions: list[str] = field(default_factory=list)
    login_required: bool = True
    login_dep: Callable | None = None
    permission_dep: PermissionDepFn | None = None

    # Hooks
    before_update: UpdateBeforeHookFn | None = None
    after_update: UpdateAfterHookFn | None = None

    # FastAPI
    dependencies: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    summary: str | None = None
