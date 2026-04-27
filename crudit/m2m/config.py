from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class M2MConfig:
    """Configuration for a many-to-many relationship router."""

    child_path_segment: str | None = None
    tags: list[str] = field(default_factory=list)
    dependencies: list[Any] = field(default_factory=list)
    login_required: bool = True
    permissions: list[str] = field(default_factory=list)