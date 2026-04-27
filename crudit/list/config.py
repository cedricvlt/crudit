from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from crudit.types import AfterFn, FilterFn, HookFn, SearchFn


@dataclass
class ListConfig:
    # Path param name → model field name, e.g. {"city_id": "city_id"}
    path_filters: dict[str, str] = field(default_factory=dict)

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

    # Hooks
    before_query: HookFn | None = None
    after_query: AfterFn | None = None

    # FastAPI
    dependencies: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
