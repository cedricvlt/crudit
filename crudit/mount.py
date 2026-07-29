from __future__ import annotations

import inspect
import re
from typing import Annotated, Any

from fastapi import APIRouter, Path
from fastapi.routing import APIRoute

_PLACEHOLDER_RE = re.compile(r"{([^}:]+)(?::[^}]*)?}")


def _infer_type(param_name: str) -> type:
    """Ancestor ids are integers; anything else is treated as a string."""
    return int if param_name.endswith("_id") else str


def _accepts_kwargs(endpoint: Any) -> bool:
    """True when the real function has a ``**kwargs`` absorber.

    Read off the code object, not ``inspect.signature``: crudit strips the
    VAR_KEYWORD entry from ``__signature__`` while the function itself keeps it.
    """
    code = getattr(endpoint, "__code__", None)
    return bool(code and code.co_flags & inspect.CO_VARKEYWORDS)


def include_nested_router(
    parent: APIRouter,
    child: APIRouter,
    *,
    prefix: str = "",
    param_types: dict[str, type] | None = None,
    **include_kwargs: Any,
) -> None:
    """
    `parent.include_router(child, prefix=prefix, ...)`, but every placeholder in
    `prefix` that a child route does not already declare is added to that route's
    signature as a typed path parameter.

    FastAPI only documents path params that appear in the endpoint signature. A
    router mounted under an ancestor prefix — e.g. a floors router under
    ``/expertises/{expertise_id}/area-buildings/{building_id}/floors``, whose own
    `path_filters` only names ``building_id`` — therefore produces an OpenAPI
    operation with no ``expertise_id`` parameter, even though the URL cannot be
    built without one. Generated clients then reject the (correct) call.

    The value is not used by the handler: it is read from `request.path_params`
    where a route needs it. This only makes the schema describe the real URL.

    Types are inferred by name (``*_id`` -> int, otherwise str) and can be
    overridden per param with `param_types`. Routes already declaring a
    placeholder keep their own (column-derived) annotation.

    Include a given child router under one prefix only: the parameters are baked
    into the endpoint signature, so mounting it a second time elsewhere would
    carry the first prefix's params along.

    Routes whose handler cannot absorb the value (no ``**kwargs``) are left
    alone — FastAPI passes every declared param as a keyword argument, so
    declaring one on such a handler would raise TypeError on every request.
    """
    placeholders = _PLACEHOLDER_RE.findall(prefix)
    if placeholders:
        types = param_types or {}
        for route in child.routes:
            if not isinstance(route, APIRoute) or not _accepts_kwargs(route.endpoint):
                continue
            sig = inspect.signature(route.endpoint)
            base = [
                p
                for p in sig.parameters.values()
                if p.kind != inspect.Parameter.VAR_KEYWORD
            ]
            declared = {p.name for p in base}
            extra = [
                inspect.Parameter(
                    name=name,
                    kind=inspect.Parameter.KEYWORD_ONLY,
                    annotation=Annotated[types.get(name) or _infer_type(name), Path()],
                )
                for name in placeholders
                if name not in declared
            ]
            if extra:
                route.endpoint.__signature__ = inspect.Signature(
                    base + extra, return_annotation=sig.return_annotation
                )
    parent.include_router(child, prefix=prefix, **include_kwargs)
