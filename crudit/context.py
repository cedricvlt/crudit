from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
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


class _HookRequest:
    """Request stand-in handed to ``(obj, request, user)``-style hooks when the
    service runs outside HTTP. Exposes the two surfaces hooks actually use:
    ``path_params`` and a mutable ``state`` shared across hooks of one call."""

    def __init__(self, ctx: CruditContext) -> None:
        self.path_params = ctx.path_params
        self.query_params = ctx.query_params
        self.state = ctx.extras.setdefault("request_state", SimpleNamespace())


def hook_request(ctx: CruditContext) -> Any:
    """Return the real request when present, else a cached per-context shim."""
    if ctx.request is not None:
        return ctx.request
    shim = ctx.extras.get("_hook_request")
    if shim is None:
        shim = _HookRequest(ctx)
        ctx.extras["_hook_request"] = shim
    return shim
