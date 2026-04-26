from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from crudit.types import PermissionDepFn, ReorderHookFn


@dataclass
class ReorderConfig:
    # Path param name → model field name, e.g. {"city_id": "city_id"}
    path_filters: dict[str, str] = field(default_factory=dict)

    # Permissions
    permissions: list[str] = field(default_factory=list)
    login_required: bool = True
    login_dep: Callable | None = None
    permission_dep: PermissionDepFn | None = None

    # Hooks
    before_reorder: ReorderHookFn | None = None
    after_reorder: ReorderHookFn | None = None

    # FastAPI
    dependencies: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    summary: str | None = None
