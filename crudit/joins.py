from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import DeclarativeBase, contains_eager, joinedload, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from crudit.exceptions import CruditConfigError


@dataclass
class JoinInfo:
    # relationship name → related SQLAlchemy model class
    joined_models: dict[str, type] = field(default_factory=dict)
    # m2o/o2o: can be explicitly joined for filter/sort
    m2o_rels: set[str] = field(default_factory=set)
    # o2m: loaded via selectin, cannot be joined for filter/sort
    o2m_rels: set[str] = field(default_factory=set)

    def eager_load_options(self, model: type, explicitly_joined: set[str]) -> list[_AbstractLoad]:
        """
        Build eager-load options given which relationships were explicitly joined
        in the query (those get contains_eager; others get joinedload/selectinload).
        """
        options = []
        for rel_name, rel_model in self.joined_models.items():
            rel_attr = getattr(model, rel_name)
            if rel_name in self.o2m_rels:
                options.append(selectinload(rel_attr))
            elif rel_name in explicitly_joined:
                options.append(contains_eager(rel_attr))
            else:
                options.append(joinedload(rel_attr))
        return options


def resolve_joins(model: type[DeclarativeBase], schema: type[BaseModel]) -> JoinInfo:
    """
    Inspect the Pydantic schema for nested BaseModel fields and match them to
    SQLAlchemy relationships. Called once at route registration time.
    """
    info = JoinInfo()
    mapper = sa_inspect(model)
    relationship_map = {r.key: r for r in mapper.relationships}

    for field_name, field_info in schema.model_fields.items():
        annotation = field_info.annotation
        rel_model, is_list = _extract_nested_model(annotation)
        if rel_model is None:
            continue

        if field_name not in relationship_map:
            raise CruditConfigError(
                f"Schema field '{field_name}' looks like a relationship "
                f"(annotated with a BaseModel subclass) but no relationship "
                f"named '{field_name}' exists on {model.__name__}."
            )

        rel = relationship_map[field_name]
        related_class = rel.mapper.class_
        info.joined_models[field_name] = related_class

        if is_list:
            info.o2m_rels.add(field_name)
        else:
            info.m2o_rels.add(field_name)

    return info


def collect_needed_joins(
    filter_params: dict[str, list[str]],
    sort_param: str | None,
    join_info: JoinInfo,
) -> set[str]:
    """
    Scan filter keys and sort param to find which m2o relationships need an
    explicit JOIN added to the query for WHERE / ORDER BY to work.
    """
    from crudit.list.filters import _RESERVED_PARAMS, _parse_key

    needed: set[str] = set()

    for raw_key in filter_params:
        if raw_key in _RESERVED_PARAMS:
            continue
        field_path, _ = _parse_key(raw_key)
        if "." in field_path:
            rel_name = field_path.split(".")[0]
            if rel_name in join_info.m2o_rels:
                needed.add(rel_name)

    if sort_param:
        for part in sort_param.split(","):
            field_path = part.strip().lstrip("-")
            if "." in field_path:
                rel_name = field_path.split(".")[0]
                if rel_name in join_info.m2o_rels:
                    needed.add(rel_name)

    return needed


def resolve_nested_column(
    field_path: str,
    model: type[DeclarativeBase],
    joined_models: dict[str, type],
) -> Any:
    """
    Resolve a dot-notation field path like "city.name" to a SQLAlchemy column.
    """
    parts = field_path.split(".", 1)
    if len(parts) == 1:
        col = getattr(model, parts[0], None)
        if col is None:
            raise ValueError(f"Field '{parts[0]}' not found on {model.__name__}.")
        return col

    rel_name, col_name = parts
    if rel_name not in joined_models:
        raise ValueError(
            f"Relationship '{rel_name}' is not joined. "
            "Only fields from joined relationships can be used for nested filter/sort."
        )
    related_model = joined_models[rel_name]
    col = getattr(related_model, col_name, None)
    if col is None:
        raise ValueError(f"Field '{col_name}' not found on {related_model.__name__}.")
    return col


def _extract_nested_model(annotation: Any) -> tuple[type[BaseModel] | None, bool]:
    import types as _types
    from typing import Union

    if annotation is None:
        return None, False

    origin = get_origin(annotation)

    # list[BaseModel] -> o2m (selectinload)
    if origin is list:
        args = get_args(annotation)
        if args and inspect.isclass(args[0]) and issubclass(args[0], BaseModel):
            return args[0], True
        return None, False

    # BaseModel | None or Optional[BaseModel] -> m2o/o2o (joinedload)
    if origin is Union or (hasattr(_types, "UnionType") and isinstance(annotation, _types.UnionType)):
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and inspect.isclass(non_none[0]) and issubclass(non_none[0], BaseModel):
            return non_none[0], False
        return None, False

    # bare BaseModel -> m2o/o2o (joinedload)
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return annotation, False

    return None, False
