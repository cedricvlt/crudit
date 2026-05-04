from __future__ import annotations

import inspect
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import Path, Query


def _get_python_type(col: Any) -> type:
    """Get the Python type of a SQLAlchemy column attribute, defaulting to str."""
    try:
        return col.property.columns[0].type.impl_instance.python_type
    except Exception:
        try:
            return col.property.columns[0].type.python_type
        except Exception:
            return str


def _make_filter_params(
    field: str,
    model: Any,
    joined_models: dict[str, type],
) -> list[inspect.Parameter]:
    """
    Build typed inspect.Parameters for a filterable field and all its operators.

    The base param uses list[<col_type>] | None (for multi-value OR equality).
    Operator-suffixed params (e.g. name__ilike, age__gte) are added for each
    operator that makes sense for the column type.
    """
    from crudit.joins import resolve_nested_column

    try:
        col = resolve_nested_column(field, model, joined_models)
        python_type = _get_python_type(col)
    except Exception:
        python_type = str

    has_dot = "." in field
    base_name = field.replace(".", "__") if has_dot else field

    def _param(suffix: str, annotation: Any) -> inspect.Parameter:
        param_name = f"{base_name}__{suffix}" if suffix else base_name
        if has_dot:
            alias = f"{field}__{suffix}" if suffix else field
            q = Query(alias=alias)
        else:
            q = Query()
        return inspect.Parameter(
            name=param_name,
            kind=inspect.Parameter.KEYWORD_ONLY,
            default=None,
            annotation=Annotated[annotation, q],
        )

    params = [_param("", list[python_type] | None)]
    params.append(_param("ne", list[python_type] | None))
    params.append(_param("isnull", bool | None))

    if python_type in (int, float):
        for op in ("lt", "lte", "gt", "gte"):
            params.append(_param(op, python_type | None))
    elif python_type is str:
        params.append(_param("like", str | None))
        params.append(_param("ilike", str | None))
    elif python_type in (date, datetime):
        tp = datetime if python_type is datetime else date
        for op in ("lt", "lte", "gt", "gte"):
            params.append(_param(op, tp | None))
        params.append(_param("year", int | None))
        params.append(_param("quarter", str | None))
        params.append(_param("month", str | None))
        params.append(_param("week", str | None))
        params.append(_param("relative", str | None))

    return params


def inject_query_params(
    handler: Any,
    filterable_fields: list[str],
    model: Any = None,
    joined_models: dict[str, type] | None = None,
) -> None:
    """
    Extend handler.__signature__ with typed query params for each filterable field.

    When model and joined_models are provided, each param is typed from the
    SQLAlchemy column type and operator-suffixed variants are also injected
    (e.g. name__ilike, age__gte) so they appear in the OpenAPI schema.

    Dotted field names (e.g. "city.name") become param name city__name with
    Query(alias="city.name") so the actual URL param stays dotted.

    The handler must declare **_filter_kwargs to absorb the injected values
    (filtering reads request.query_params directly, not these params).
    """
    existing_sig = inspect.signature(handler)
    base_params = [
        p
        for p in existing_sig.parameters.values()
        if p.kind != inspect.Parameter.VAR_KEYWORD
    ]
    filter_params: list[inspect.Parameter] = []
    for field in filterable_fields:
        if model is not None:
            filter_params.extend(_make_filter_params(field, model, joined_models or {}))
        else:
            if "." in field:
                param_name = field.replace(".", "__")
                annotation = Annotated[list[str] | None, Query(alias=field)]
            else:
                param_name = field
                annotation = Annotated[list[str] | None, Query()]
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


def inject_path_params(
    handler: Any,
    path_filters: dict[str, str],
    model: Any,
) -> None:
    """
    Extend handler.__signature__ with typed path params for each entry in
    path_filters so they are exposed in the OpenAPI schema.

    The Python type of each param is inferred from the SQLAlchemy column it
    maps onto. Path params have no default and FastAPI marks them required.
    The handler must absorb them via **_path_kwargs (the actual value is
    read from request.path_params at runtime).

    Always normalises the signature by stripping VAR_KEYWORD, so FastAPI
    does not mistake the absorber for a body/query field even when no path
    filters are configured.
    """
    existing_sig = inspect.signature(handler)
    base_params = [
        p
        for p in existing_sig.parameters.values()
        if p.kind != inspect.Parameter.VAR_KEYWORD
    ]
    existing_names = {p.name for p in base_params}
    new_params: list[inspect.Parameter] = []
    for param_name, field_name in (path_filters or {}).items():
        if param_name in existing_names:
            continue
        col = getattr(model, field_name, None)
        python_type = _get_python_type(col) if col is not None else str
        new_params.append(
            inspect.Parameter(
                name=param_name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                annotation=Annotated[python_type, Path()],
            )
        )
    handler.__signature__ = inspect.Signature(
        base_params + new_params,
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
