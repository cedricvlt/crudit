from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.sql import Select
from starlette.requests import Request

# (query, raw_value, current_user) -> query
FilterFn = Callable[[Select, str, Any], Select]

# (query, raw_value, current_user) -> query
SearchFn = Callable[[Select, str, Any], Select]

# (query, request, current_user) -> query
HookFn = Callable[[Select, Request, Any], Select]

# (results, request, current_user) -> results
AfterFn = Callable[[list[Any], Request, Any], list[Any]]

# (row, request, current_user) -> row
ReadAfterFn = Callable[[Any, Request, Any], Any]

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

# (current_user, required_permissions) -> bool
PermissionChecker = Callable[[Any, list[str]], bool]
