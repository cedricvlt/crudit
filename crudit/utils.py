from __future__ import annotations

import asyncio
from typing import Any, Callable

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
