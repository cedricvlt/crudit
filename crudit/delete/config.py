from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from crudit.types import DeleteHookFn, PermissionDepFn


@dataclass
class DeleteConfig:
    # Permissions
    permissions: list[str] = field(default_factory=list)
    login_required: bool = True
    login_dep: Callable | None = None
    permission_dep: PermissionDepFn | None = None

    # Hooks
    before_delete: DeleteHookFn | None = None
    after_delete: DeleteHookFn | None = None

    # FastAPI
    dependencies: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    summary: str | None = None
