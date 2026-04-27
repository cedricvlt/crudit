from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable

from fastapi import Depends


async def _no_user() -> None:
    return None


_NO_USER_DEP = Depends(_no_user)


def user_dep_or_none(login_dep: Callable | None) -> Any:
    """Return Depends(login_dep) if provided, else a no-op Depends that returns None.

    Using a bare None default for current_user causes FastAPI to expose it as a
    query parameter in the OpenAPI schema.  A Depends that resolves to None is
    invisible to OpenAPI and avoids this leak.
    """
    return Depends(login_dep) if login_dep else _NO_USER_DEP

_ERROR_DESCRIPTIONS: dict[int, str] = {
    400: "Bad request (missing path parameter or validation error)",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not found",
    422: "Unprocessable entity",
    500: "Internal server error",
}


def get_error_responses(*codes: int) -> dict[int, dict[str, str]]:
    """Return an OpenAPI `responses` dict for the given HTTP error status codes."""
    return {code: {"description": _ERROR_DESCRIPTIONS[code]} for code in codes}


async def call_hook(fn: Callable, *args: Any) -> Any:
    """Call a sync or async hook function with *args and return its result."""
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args)
    return fn(*args)


def bind_perms(permission_dep: Callable, perms: list[str]) -> Callable:
    """
    Call permission_dep(*perms) to obtain the actual FastAPI dependency.

    permission_dep must be a factory: a plain callable that accepts the permission
    codes as positional *args and returns a FastAPI dependency function (which may
    itself use Depends() for its own parameters).  The library calls the factory
    once at route-registration time so no permission-related parameters are ever
    visible to FastAPI or shown in the OpenAPI schema.
    """
    return permission_dep(*perms)
