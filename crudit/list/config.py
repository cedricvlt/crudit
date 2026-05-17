from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import DeclarativeBase

from crudit.types import AfterFn, FilterFn, HookFn, SearchFn


@dataclass
class ListConfig:
    # Permissions
    permissions: list[str] = field(default_factory=list)
    login_required: bool = True

    # Filters — plain field names or "relationship.field" notation
    filterable_fields: list[str] = field(default_factory=list)
    filter_fns: dict[str, FilterFn] = field(default_factory=dict)

    # Sort whitelist — plain or "relationship.field"
    sortable_fields: list[str] = field(default_factory=list)

    # Global search
    search_fields: list[str] = field(default_factory=list)
    search_fn: SearchFn | None = None

    # Always-applied filters, not exposed as URL params
    default_filters: dict[str, Any] = field(default_factory=dict)

    # Computed fields — name -> callable(model_cls) returning a SQL scalar
    # expression (typically a correlated subquery). Each is injected as a
    # labeled column on the main SELECT and attached to each row before
    # Pydantic validation. The response schema must declare these fields.
    computed_fields: dict[str, Callable[[type[DeclarativeBase]], Any]] = field(
        default_factory=dict
    )

    # Hooks
    before_query: HookFn | None = None
    after_query: AfterFn | None = None

    # FastAPI
    dependencies: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    operation_id: str | None = None
