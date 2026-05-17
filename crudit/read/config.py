from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import DeclarativeBase

from crudit.types import HookFn, ReadAfterFn


@dataclass
class ReadConfig:
    # Permissions
    permissions: list[str] = field(default_factory=list)
    login_required: bool = True

    # Computed fields — name -> callable(model_cls) returning a SQL scalar
    # expression. Injected as labeled columns on the SELECT and attached to
    # the row before Pydantic validation. The response schema must declare
    # these fields.
    computed_fields: dict[str, Callable[[type[DeclarativeBase]], Any]] = field(
        default_factory=dict
    )

    # Hooks
    before_query: HookFn | None = None
    after_query: ReadAfterFn | None = None

    # FastAPI
    dependencies: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    operation_id: str | None = None
