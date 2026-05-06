from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from crudit.types import HookFn, ReadAfterFn


@dataclass
class ReadConfig:
    # Permissions
    permissions: list[str] = field(default_factory=list)
    login_required: bool = True

    # Hooks
    before_query: HookFn | None = None
    after_query: ReadAfterFn | None = None

    # FastAPI
    dependencies: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    operation_id: str | None = None
