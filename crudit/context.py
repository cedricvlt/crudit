from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starlette.requests import Request


@dataclass
class CruditContext:
    """Execution context passed to hooks and service-layer callables.

    Hooks receive ``(payload, ctx)`` instead of the FastAPI ``Request`` so that
    the same business logic can be invoked from non-HTTP callers (MCP tools,
    background jobs, CLIs). When called from FastAPI, ``request`` carries the
    underlying Starlette request; from other callers it is ``None``.
    """

    user: Any = None
    path_params: dict[str, Any] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    request: "Request | None" = None
    extras: dict[str, Any] = field(default_factory=dict)
