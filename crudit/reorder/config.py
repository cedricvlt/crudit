from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from crudit.types import ReorderHookFn


@dataclass
class ReorderConfig:
    # Permissions
    permissions: list[str] = field(default_factory=list)
    login_required: bool = True

    # Hooks
    before_reorder: ReorderHookFn | None = None
    after_reorder: ReorderHookFn | None = None

    # FastAPI
    dependencies: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
