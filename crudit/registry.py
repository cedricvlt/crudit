"""Process-wide registry of crud_router / m2m_router declarations.

Every ``crud_router()`` / ``m2m_router()`` call records what it was built from
(model, schemas, resolved per-verb configs) so non-HTTP consumers — an MCP
server, background jobs — can drive the same service layer without a parallel
hand-written catalogue.

The registry is append-only and performs no de-duplication: consumers decide
how to resolve collisions (e.g. raise on duplicate entity types). Tests should
call :func:`reset` between cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from pydantic import BaseModel

if TYPE_CHECKING:
    from crudit.create.config import CreateConfig
    from crudit.delete.config import DeleteConfig
    from crudit.list.config import ListConfig
    from crudit.m2m.service import M2MSpec
    from crudit.read.config import ReadConfig
    from crudit.update.config import UpdateConfig


@dataclass
class CrudDeclaration:
    """One ``crud_router()`` call, with per-verb configs resolved (None when
    the verb is not registered)."""

    entity_type: str
    description: str
    model: type
    list_item_schema: type[BaseModel] | None = None
    read_schema: type[BaseModel] | None = None
    create_schema: type[BaseModel] | None = None
    # The create schema with path-filter fields stripped — what the HTTP body
    # actually accepts. Equal to ``create_schema`` when there are no filters.
    body_create_schema: type[BaseModel] | None = None
    update_schema: type[BaseModel] | None = None
    list_config: "ListConfig | None" = None
    read_config: "ReadConfig | None" = None
    create_config: "CreateConfig | None" = None
    update_config: "UpdateConfig | None" = None
    delete_config: "DeleteConfig | None" = None
    path_filters: dict[str, str] = field(default_factory=dict)
    # The login dependency the routes were registered with. Consumers can
    # inspect it to mirror route-level auth (e.g. staff-only routers).
    login_dep: Callable | None = None
    # Lean read schema exposed to MCP-style consumers instead of read_schema.
    mcp_read_schema: type[BaseModel] | None = None
    # Verb names hidden from MCP-style consumers ("create", "delete", ... or "*").
    mcp_exclude: frozenset[str] = frozenset()


@dataclass
class M2MDeclaration:
    """One ``m2m_router()`` call."""

    relation: str
    spec: "M2MSpec"
    parent_model: type
    child_model: type
    login_dep: Callable | None = None


_cruds: list[CrudDeclaration] = []
_m2ms: list[M2MDeclaration] = []


def register_crud(declaration: CrudDeclaration) -> None:
    _cruds.append(declaration)


def register_m2m(declaration: M2MDeclaration) -> None:
    _m2ms.append(declaration)


def iter_cruds() -> tuple[CrudDeclaration, ...]:
    return tuple(_cruds)


def iter_m2ms() -> tuple[M2MDeclaration, ...]:
    return tuple(_m2ms)


def reset() -> None:
    """Clear the registry (test isolation)."""
    _cruds.clear()
    _m2ms.clear()
