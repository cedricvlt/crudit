from __future__ import annotations

import asyncio
from typing import Any, Callable


async def call_hook(fn: Callable, *args: Any) -> Any:
    """Call a sync or async hook function with *args and return its result."""
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args)
    return fn(*args)
