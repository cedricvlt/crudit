from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from crudit.types import HookFn, PermissionChecker, ReadAfterFn


@dataclass
class ReadConfig:
    # Permissions
    permissions: list[str] = field(default_factory=list)
    login_required: bool = True
    login_dep: Callable | None = None
    permission_checker: PermissionChecker | None = None

    # Hooks
    before_query: HookFn | None = None
    after_query: ReadAfterFn | None = None

    # FastAPI
    dependencies: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    summary: str | None = None
