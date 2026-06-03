from __future__ import annotations

import inspect
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import DeclarativeBase, contains_eager, joinedload, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad
from sqlalchemy.sql import Select

from crudit.exceptions import CruditConfigError


def _get_property_names(model: type) -> set[str]:
    """Return names of plain Python @property attributes on the model.

    Walks the MRO so properties defined on a base class are picked up.
    `hybrid_property` is not a `property` subclass, so it is correctly
    excluded — those have a SQL expression form and can stay in queries.
    """
    names: set[str] = set()
    for klass in model.__mro__:
        for attr_name, attr in vars(klass).items():
            if isinstance(attr, property):
                names.add(attr_name)
    return names


@dataclass
class JoinNode:
    """One relationship in the resolved join tree.

    `model` is the related SQLAlchemy class. `is_collection` is True for
    o2m relationships (loaded via selectinload). `children` holds further
    relationships discovered on the nested Pydantic schema.
    """
    rel_name: str
    model: type
    is_collection: bool
    children: dict[str, "JoinNode"] = field(default_factory=dict)


@dataclass
class JoinInfo:
    # Top-level relationships keyed by name; nested relationships live in
    # JoinNode.children. The tree mirrors the nested structure of the
    # Pydantic schema passed to resolve_joins().
    nodes: dict[str, JoinNode] = field(default_factory=dict)

    # Names of @property attributes on the *root* model. These are schema
    # fields evaluated in Python (via Pydantic's from_attributes=True) and
    # must never appear in filter/sort/search lists.
    property_fields: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------
    # Tree walking helpers
    # ------------------------------------------------------------------

    def find_node(self, path: str) -> JoinNode | None:
        """Return the JoinNode at a dotted path (e.g. "city.country") or None."""
        nodes = self.nodes
        node: JoinNode | None = None
        for part in path.split("."):
            node = nodes.get(part)
            if node is None:
                return None
            nodes = node.children
        return node

    def is_m2o_chain(self, rel_path: str) -> bool:
        """True if every segment in the dotted path is a m2o relationship.

        Only m2o chains can be JOINed for filter/sort/search — joining an
        o2m would multiply rows.
        """
        nodes = self.nodes
        for part in rel_path.split("."):
            node = nodes.get(part)
            if node is None or node.is_collection:
                return False
            nodes = node.children
        return True

    def parent_model_for(self, root_model: type, rel_path: str) -> type:
        """Return the model class that owns the *last* segment of `rel_path`.

        For "city.country", returns the City model (parent of `country`).
        Raises KeyError if the path is not in the tree.
        """
        parts = rel_path.split(".")
        nodes = self.nodes
        parent_model: type = root_model
        for rel_name in parts[:-1]:
            node = nodes[rel_name]
            parent_model = node.model
            nodes = node.children
        if parts[-1] not in nodes:
            raise KeyError(rel_path)
        return parent_model

    # ------------------------------------------------------------------
    # Per-request join application
    # ------------------------------------------------------------------

    def apply_explicit_joins(
        self,
        query: Select,
        root_model: type,
        explicitly_joined: set[str],
    ) -> Select:
        """Add chained outer JOINs to `query` for each path in `explicitly_joined`.

        Paths are sorted by depth so parents are joined before children.
        """
        for join_path in sorted(explicitly_joined, key=lambda p: p.count(".")):
            parent_model = self.parent_model_for(root_model, join_path)
            rel_attr = getattr(parent_model, join_path.rsplit(".", 1)[-1])
            query = query.join(rel_attr, isouter=True)
        return query

    # ------------------------------------------------------------------
    # Eager loading
    # ------------------------------------------------------------------

    def eager_load_options(
        self,
        model: type,
        explicitly_joined: set[str],
    ) -> list[_AbstractLoad]:
        """Build chained eager-load options for the whole join tree.

        For each leaf in the tree, emit one chained Load option that walks
        from the root to the leaf. Intermediate m2o segments use
        `contains_eager` when explicitly joined (so the loaded JOIN is
        consumed) and `joinedload` otherwise. o2m segments always use
        `selectinload`.
        """
        options: list[_AbstractLoad] = []
        for rel_name, node in self.nodes.items():
            self._collect_options(model, node, rel_name, explicitly_joined, None, options)
        return options

    def _collect_options(
        self,
        parent_model: type,
        node: JoinNode,
        path: str,
        explicitly_joined: set[str],
        base_opt: _AbstractLoad | None,
        options: list[_AbstractLoad],
    ) -> None:
        rel_attr = getattr(parent_model, node.rel_name)
        opt = self._step_load(base_opt, rel_attr, node.is_collection, path, explicitly_joined)

        if not node.children:
            options.append(opt)
            return

        for child_name, child_node in node.children.items():
            child_path = f"{path}.{child_name}"
            self._collect_options(
                node.model, child_node, child_path, explicitly_joined, opt, options
            )

    @staticmethod
    def _step_load(
        base_opt: _AbstractLoad | None,
        rel_attr: Any,
        is_collection: bool,
        path: str,
        explicitly_joined: set[str],
    ) -> _AbstractLoad:
        if is_collection:
            return base_opt.selectinload(rel_attr) if base_opt else selectinload(rel_attr)
        if path in explicitly_joined:
            return base_opt.contains_eager(rel_attr) if base_opt else contains_eager(rel_attr)
        return base_opt.joinedload(rel_attr) if base_opt else joinedload(rel_attr)

    # ------------------------------------------------------------------
    # Post-load: sort o2m collections by their _order_fields
    # ------------------------------------------------------------------

    def sort_o2m_collections(self, rows: list) -> None:
        """Sort each loaded o2m collection (at any depth) by `_order_fields`.

        Mutates rows in-place. Null values sort last and never compare
        against non-null values of mixed types.
        """
        for row in rows:
            self._sort_recursive(row, self.nodes)

    def _sort_recursive(self, obj: Any, nodes: dict[str, JoinNode]) -> None:
        if obj is None:
            return
        for rel_name, node in nodes.items():
            attr = getattr(obj, rel_name, None)
            if attr is None:
                continue
            if node.is_collection:
                order_fields: tuple[str, ...] = getattr(node.model, "_order_fields", ())
                if order_fields:
                    attr.sort(key=lambda o: tuple(
                        ((v := getattr(o, f, None)) is None, v)
                        for f in order_fields
                    ))
                if node.children:
                    for item in attr:
                        self._sort_recursive(item, node.children)
            else:
                if node.children:
                    self._sort_recursive(attr, node.children)


def resolve_joins(model: type[DeclarativeBase], schema: type[BaseModel]) -> JoinInfo:
    """Inspect the Pydantic schema for nested BaseModel fields and match them
    to SQLAlchemy relationships, recursing into nested schemas to build a
    full join tree. Called once at route registration time.
    """
    info = JoinInfo(property_fields=_get_property_names(model))
    _populate_nodes(model, schema, info.nodes)
    return info


def _populate_nodes(
    model: type,
    schema: type[BaseModel],
    nodes: dict[str, JoinNode],
) -> None:
    mapper = sa_inspect(model)
    relationship_map = {r.key: r for r in mapper.relationships}
    property_names = _get_property_names(model)

    for field_name, field_info in schema.model_fields.items():
        annotation = field_info.annotation
        rel_schema, is_list = _extract_nested_model(annotation)
        if rel_schema is None:
            continue

        if field_name not in relationship_map:
            # A @property returning a BaseModel is fine — Pydantic will
            # evaluate it from the ORM instance after the query runs. Skip
            # relationship resolution; nothing needs to load.
            if field_name in property_names:
                continue
            raise CruditConfigError(
                f"Schema field '{field_name}' looks like a relationship "
                f"(annotated with a BaseModel subclass) but no relationship "
                f"named '{field_name}' exists on {model.__name__}."
            )

        rel = relationship_map[field_name]
        related_class = rel.mapper.class_

        node = JoinNode(rel_name=field_name, model=related_class, is_collection=is_list)
        _populate_nodes(related_class, rel_schema, node.children)
        nodes[field_name] = node


def assert_no_property_fields(
    field_paths: Iterable[str],
    model: type,
    join_info: JoinInfo,
    *,
    context: str,
) -> None:
    """Raise CruditConfigError if any path resolves to a @property attribute.

    Properties are evaluated in Python and have no SQL form, so they cannot
    appear in `filterable_fields`, `sortable_fields`, or `search_fields`.

    Walks dotted paths through the join tree: every non-leaf segment must
    be a relationship; the leaf is checked against the final model's
    @property names.
    """
    for path in field_paths:
        parts = path.split(".")
        nodes = join_info.nodes
        current_model: type = model
        for rel_name in parts[:-1]:
            node = nodes.get(rel_name)
            if node is None:
                # The intermediate segment is missing from the join tree.
                # If it's a property on the current model, flag it here.
                # Otherwise, leave it for the existing request-time validation
                # to report.
                if rel_name in _get_property_names(current_model):
                    raise CruditConfigError(
                        f"'{rel_name}' on {current_model.__name__} is a @property, "
                        f"not a SQL column — it cannot be used in {context}."
                    )
                break
            current_model = node.model
            nodes = node.children
        else:
            leaf = parts[-1]
            if leaf in _get_property_names(current_model):
                raise CruditConfigError(
                    f"'{leaf}' on {current_model.__name__} is a @property, "
                    f"not a SQL column — it cannot be used in {context}."
                )


def collect_sortable_field_paths(
    model: type[DeclarativeBase],
    schema: type[BaseModel],
    join_info: JoinInfo,
) -> list[str]:
    """Return every dotted field path in `schema` that is backed by a SQL
    column and reachable through m2o relationships.

    Used to auto-default `sortable_fields` so that any field the API exposes
    is sortable without having to list it again. Skips:
    - scalar fields not in the model's mapper columns (e.g. @property,
      hybrid_property, fields not on the ORM model);
    - o2m relationships (`list[BaseModel]`) — sorting through a collection
      would multiply rows;
    - nested BaseModel fields with no matching relationship in the join tree
      (e.g. @property returning a BaseModel).
    """
    out: list[str] = []
    _walk_sortable(model, schema, join_info.nodes, "", out)
    return out


def _walk_sortable(
    model: type,
    schema: type[BaseModel],
    nodes: dict[str, JoinNode],
    prefix: str,
    out: list[str],
) -> None:
    column_names = {c.key for c in sa_inspect(model).columns}
    for field_name, field_info in schema.model_fields.items():
        rel_schema, is_list = _extract_nested_model(field_info.annotation)
        path = f"{prefix}.{field_name}" if prefix else field_name
        if rel_schema is None:
            if field_name in column_names:
                out.append(path)
            continue
        if is_list:
            continue
        node = nodes.get(field_name)
        if node is None:
            continue
        _walk_sortable(node.model, rel_schema, node.children, path, out)


def collect_needed_joins(
    filter_params: dict[str, list[str]],
    sort_param: str | None,
    join_info: JoinInfo,
    search_fields: list[str] | None = None,
) -> set[str]:
    """Scan filter keys, sort param, and search fields to find which m2o
    relationship paths need explicit JOINs added to the query.

    Returns a set of dotted relationship paths (every prefix on the chain),
    e.g. {"city", "city.country"} for a filter on "city.country.name".
    Paths whose chain includes an o2m segment are skipped — they cannot be
    used for filter/sort/search and `resolve_nested_column` will raise.
    """
    from crudit.list.filters import _RESERVED_PARAMS, _parse_key

    needed: set[str] = set()

    def add_field_path(field_path: str) -> None:
        if "." not in field_path:
            return
        rel_parts = field_path.split(".")[:-1]
        nodes = join_info.nodes
        prefix = ""
        prefixes: list[str] = []
        for rel_name in rel_parts:
            node = nodes.get(rel_name)
            if node is None or node.is_collection:
                # A collection (or missing) segment means the whole path is
                # resolved via an EXISTS subquery, not a JOIN — drop any m2o
                # prefixes accumulated so far so we never emit a stray JOIN.
                return
            prefix = f"{prefix}.{rel_name}" if prefix else rel_name
            prefixes.append(prefix)
            nodes = node.children
        needed.update(prefixes)

    for raw_key in filter_params:
        if raw_key in _RESERVED_PARAMS:
            continue
        field_path, _ = _parse_key(raw_key)
        add_field_path(field_path)

    if sort_param:
        for part in sort_param.split(","):
            add_field_path(part.strip().lstrip("-"))

    if search_fields:
        for field_path in search_fields:
            add_field_path(field_path)

    return needed


def resolve_nested_column(
    field_path: str,
    model: type[DeclarativeBase],
    join_info: JoinInfo,
) -> Any:
    """Resolve an arbitrary-depth dotted path like "city.country.name" to a
    SQLAlchemy column.

    Every intermediate segment must be a joined m2o relationship.
    """
    parts = field_path.split(".")
    if len(parts) == 1:
        col = getattr(model, parts[0], None)
        if col is None:
            raise ValueError(f"Field '{parts[0]}' not found on {model.__name__}.")
        return col

    *rel_parts, col_name = parts
    nodes = join_info.nodes
    current_model: type = model
    walked = ""
    for rel_name in rel_parts:
        walked = f"{walked}.{rel_name}" if walked else rel_name
        node = nodes.get(rel_name)
        if node is None:
            raise ValueError(
                f"Relationship '{walked}' is not joined. "
                "Only fields from joined relationships can be used for nested filter/sort."
            )
        if node.is_collection:
            raise ValueError(
                f"Cannot use '{field_path}' for filter/sort/search: "
                f"'{walked}' is a collection (o2m) relationship."
            )
        current_model = node.model
        nodes = node.children

    col = getattr(current_model, col_name, None)
    if col is None:
        raise ValueError(f"Field '{col_name}' not found on {current_model.__name__}.")
    return col


def resolve_filter_path(
    field_path: str,
    model: type[DeclarativeBase],
    join_info: JoinInfo,
) -> tuple[Any, list[tuple[Any, bool]]]:
    """Resolve a dotted filter path to ``(leaf_col, wrappers)``.

    ``wrappers`` is a list of ``(relationship_attr, is_collection)`` tuples,
    ordered outermost-first, that the caller wraps the leaf comparison in via
    ``.any()`` (collection) / ``.has()`` (scalar) — applied innermost-first.

    Two resolution modes:

    - **Pure many-to-one chains** (or a plain column): ``wrappers`` is empty and
      the leaf is resolved with :func:`resolve_nested_column`, preserving the
      existing JOIN-based behavior, the response-schema requirement, and the
      error messages exactly.
    - **Chains traversing a collection** (o2m / m2m): resolved directly from the
      SQLAlchemy mapper — *independent of the response schema* — so a collection
      can be filtered without being declared on the schema. Filtering uses an
      ``EXISTS`` subquery, which neither multiplies rows nor needs a JOIN.
    """
    if "." not in field_path:
        return resolve_nested_column(field_path, model, join_info), []

    *rel_parts, col_name = field_path.split(".")
    wrappers: list[tuple[Any, bool]] = []
    current_model: type = model
    walked = ""
    for rel_name in rel_parts:
        walked = f"{walked}.{rel_name}" if walked else rel_name
        rel = sa_inspect(current_model).relationships.get(rel_name)
        if rel is None:
            raise ValueError(
                f"Relationship '{walked}' not found on {model.__name__}."
            )
        wrappers.append((getattr(current_model, rel_name), bool(rel.uselist)))
        current_model = rel.mapper.class_

    # Pure m2o chain: defer to the JOIN-based resolver (behavior unchanged).
    if not any(is_collection for _, is_collection in wrappers):
        return resolve_nested_column(field_path, model, join_info), []

    col = getattr(current_model, col_name, None)
    if col is None:
        raise ValueError(f"Field '{col_name}' not found on {current_model.__name__}.")
    return col, wrappers


def is_foreign_key_column(col: Any) -> bool:
    """Return True if ``col`` maps to a foreign-key column.

    Range operators (``lt``/``lte``/``gt``/``gte``) are meaningless on a foreign
    key (e.g. ``company_id``), so they are neither advertised in the OpenAPI
    schema nor accepted at runtime for such fields. A plain primary key like
    ``id`` is *not* affected — ordering comparisons on it remain available.
    Anything that is not a mapped column (e.g. a computed scalar subquery) is
    treated as a non-foreign-key column.
    """
    try:
        column = col.property.columns[0]
    except Exception:  # noqa: BLE001
        return False
    return bool(column.foreign_keys)


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
