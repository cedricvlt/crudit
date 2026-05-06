from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from crudit.types import DeleteHookFn


@dataclass
class DeleteConfig:
    # Permissions
    permissions: list[str] = field(default_factory=list)
    login_required: bool = True

    # Hooks
    before_delete: DeleteHookFn | None = None
    after_delete: DeleteHookFn | None = None

    # FastAPI
    dependencies: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    operation_id: str | None = None
