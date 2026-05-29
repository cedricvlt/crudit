from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.sql import Select
from starlette.requests import Request

from crudit.context import CruditContext

# (query, raw_value, current_user) -> query
FilterFn = Callable[[Select, str, Any], Select]

# (query, raw_value, current_user) -> query
SearchFn = Callable[[Select, str, Any], Select]

# (query, ctx) -> query
HookFn = Callable[[Select, CruditContext], Select]

# (results, ctx) -> results
AfterFn = Callable[[list[Any], CruditContext], list[Any]]

# (row, ctx) -> row
ReadAfterFn = Callable[[Any, CruditContext], Any]

# (obj, request, current_user) -> obj  (create hooks)
CreateHookFn = Callable[[Any, Request, Any], Any]

# (obj, request, current_user) -> value  (field setter)
FieldSetterFn = Callable[[Any, Request, Any], Any]

# (obj, patch_data, request, current_user) -> patch_data  (update before hook)
UpdateBeforeHookFn = Callable[[Any, dict[str, Any], Request, Any], dict[str, Any]]

# (obj, request, current_user) -> obj  (update after hook)
UpdateAfterHookFn = Callable[[Any, Request, Any], Any]

# (obj, request, current_user) -> None  (delete hooks)
DeleteHookFn = Callable[[Any, Request, Any], None]

# (objects, request, current_user) -> None  (reorder hooks)
ReorderHookFn = Callable[[list[Any], Request, Any], None]

# (parent_id, child_ids, session, current_user) -> None  (m2m add/remove hooks)
M2MHookFn = Callable[[int, list[int], Any, Any], Any]

# plain FastAPI dependency callable (same form as login_dep)
PermissionDepFn = Callable[..., Any]
