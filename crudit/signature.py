from __future__ import annotations

import inspect
from typing import Annotated, Any

from fastapi import Query


def inject_query_params(handler: Any, filterable_fields: list[str]) -> None:
    """
    Extend handler.__signature__ with explicit query params for each filterable field.

    Simple field names (e.g. "name") become `name: str | None = None`.
    Dotted field names (e.g. "city.name") become `city__name: str | None = None`
    with a Query(alias="city.name") so the actual query param name stays dotted.

    The handler must declare **_filter_kwargs to absorb the injected values at
    call time (we still read filters from request.query_params to support operators).
    """
    existing_sig = inspect.signature(handler)
    base_params = [
        p
        for p in existing_sig.parameters.values()
        if p.kind != inspect.Parameter.VAR_KEYWORD
    ]
    filter_params = []
    for field in filterable_fields:
        if "." in field:
            param_name = field.replace(".", "__")
            annotation = Annotated[str | None, Query(alias=field)]
        else:
            param_name = field
            annotation = str | None
        filter_params.append(
            inspect.Parameter(
                name=param_name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=annotation,
            )
        )
    handler.__signature__ = inspect.Signature(
        base_params + filter_params,
        return_annotation=existing_sig.return_annotation,
    )


def patch_param_annotation(handler: Any, name: str, annotation: type) -> None:
    """
    Replace the annotation of parameter `name` in handler.__signature__.

    Use this to give FastAPI the real type for dynamically-typed parameters such
    as the `id` path param (whose Python type depends on the model's primary key)
    or the `body` request-body param (whose schema is config-driven).
    """
    existing_sig = inspect.signature(handler)
    new_params = [
        p.replace(annotation=annotation) if p.name == name else p
        for p in existing_sig.parameters.values()
    ]
    handler.__signature__ = inspect.Signature(
        new_params,
        return_annotation=existing_sig.return_annotation,
    )
