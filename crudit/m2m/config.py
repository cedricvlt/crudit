from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from crudit.types import M2MHookFn


@dataclass
class M2MConfig:
    """Configuration for a many-to-many relationship router."""

    child_path_segment: str | None = None
    tags: list[str] = field(default_factory=list)
    dependencies: list[Any] = field(default_factory=list)
    login_required: bool = True
    permissions: list[str] = field(default_factory=list)
    list_operation_id: str | None = None
    add_operation_id: str | None = None
    remove_operation_id: str | None = None
    reorder_operation_id: str | None = None
    # Name of the association-table column holding each link's position. Setting
    # it makes the relationship ordered: the list endpoint sorts by it, newly
    # added links are appended after the existing ones, and a
    # ``POST {base_path}/reorder`` endpoint is registered. Unordered when None.
    order_column: str | None = None
    # Called after links are inserted/deleted/reordered, before commit, in the
    # same transaction: (parent_id, child_ids, session, current_user). child_ids
    # holds only the ids actually added (add) or the requested ids (remove /
    # reorder).
    after_add: M2MHookFn | None = None
    after_remove: M2MHookFn | None = None
    after_reorder: M2MHookFn | None = None