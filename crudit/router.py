from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase

from crudit.create.config import CreateConfig
from crudit.create.endpoint import create_endpoint
from crudit.delete.config import DeleteConfig
from crudit.delete.endpoint import delete_endpoint
from crudit.exceptions import CruditConfigError
from crudit.list.config import ListConfig
from crudit.list.endpoint import list_endpoint
from crudit.options.config import OptionsConfig
from crudit.options.endpoint import options_endpoint
from crudit.read.config import ReadConfig
from crudit.read.endpoint import read_endpoint
from crudit.reorder.config import ReorderConfig
from crudit.reorder.endpoint import reorder_endpoint
from crudit.types import PermissionChecker
from crudit.update.config import UpdateConfig
from crudit.update.endpoint import update_endpoint

_ALL_ENDPOINTS = ["list", "read", "create", "update", "delete", "options", "reorder"]


@dataclass
class SharedConfig:
    """Auth/FastAPI defaults applied to any verb that has no explicit per-verb config."""

    permissions: list[str] = field(default_factory=list)
    login_required: bool = True
    login_dep: Callable | None = None
    permission_checker: PermissionChecker | None = None
    dependencies: list[Any] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def _from_shared(config_cls: type, shared: SharedConfig | None, **extra: Any) -> Any:
    if shared is None:
        return config_cls(**extra)
    return config_cls(
        permissions=shared.permissions,
        login_required=shared.login_required,
        login_dep=shared.login_dep,
        permission_checker=shared.permission_checker,
        dependencies=shared.dependencies,
        tags=shared.tags,
        **extra,
    )


def crud_router(
    model: type[DeclarativeBase],
    *,
    list_item_schema: type[BaseModel] | None = None,
    read_schema: type[BaseModel] | None = None,
    create_schema: type[BaseModel] | None = None,
    update_schema: type[BaseModel] | None = None,
    get_db: Callable,
    endpoints: list[str] | None = None,
    shared: SharedConfig | None = None,
    list: ListConfig | None = None,
    read: ReadConfig | None = None,
    create: CreateConfig | None = None,
    update: UpdateConfig | None = None,
    delete: DeleteConfig | None = None,
    options: OptionsConfig | None = None,
    reorder: ReorderConfig | None = None,
) -> APIRouter:
    """
    Build and return an APIRouter with a configurable set of CRUD endpoints.

    Defaults to all seven verbs: list, read, create, update, delete, options, reorder.
    Pass `endpoints` to restrict which ones are registered.

    `shared` provides default auth/FastAPI fields for any verb without an explicit
    per-verb config. When a per-verb config is given it is used as-is.

    Schema routing:
      list    → list_item_schema
      read    → read_schema
      create  → create_schema (input) + read_schema (output)
      update  → update_schema (input) + read_schema (output)
      options → list_item_schema for join resolution (output is always OptionItem)
      reorder → no schema
    """
    active = set(endpoints if endpoints is not None else _ALL_ENDPOINTS)

    unknown = active - set(_ALL_ENDPOINTS)
    if unknown:
        raise CruditConfigError(
            f"Unknown endpoint name(s): {sorted(unknown)}. Valid: {_ALL_ENDPOINTS}"
        )

    if "list" in active and list_item_schema is None:
        raise CruditConfigError("list_item_schema is required when 'list' is in endpoints.")
    if "read" in active and read_schema is None:
        raise CruditConfigError("read_schema is required when 'read' is in endpoints.")
    if "create" in active:
        if create_schema is None:
            raise CruditConfigError("create_schema is required when 'create' is in endpoints.")
        if read_schema is None:
            raise CruditConfigError("read_schema is required when 'create' is in endpoints.")
    if "update" in active:
        if update_schema is None:
            raise CruditConfigError("update_schema is required when 'update' is in endpoints.")
        if read_schema is None:
            raise CruditConfigError("read_schema is required when 'update' is in endpoints.")
    if "options" in active and options is None:
        raise CruditConfigError(
            "'options' endpoint requires an explicit OptionsConfig (with label_field or label_fn). "
            "Pass options=OptionsConfig(...) or remove 'options' from endpoints."
        )

    router = APIRouter()

    if "list" in active:
        list_cfg = list or _from_shared(ListConfig, shared)
        list_endpoint(router, "", model, list_item_schema, list_cfg, get_db=get_db)

    if "create" in active:
        create_cfg = create or _from_shared(CreateConfig, shared)
        create_endpoint(router, "", model, create_schema, read_schema, create_cfg, get_db=get_db)

    if "read" in active:
        read_cfg = read or _from_shared(ReadConfig, shared)
        read_endpoint(router, "/{id}", model, read_schema, read_cfg, get_db=get_db)

    if "update" in active:
        update_cfg = update or _from_shared(UpdateConfig, shared)
        update_endpoint(router, "/{id}", model, update_schema, read_schema, update_cfg, get_db=get_db)

    if "delete" in active:
        delete_cfg = delete or _from_shared(DeleteConfig, shared)
        delete_endpoint(router, "/{id}", model, delete_cfg, get_db=get_db)

    if "options" in active:
        options_endpoint(router, "/options", model, options, schema=list_item_schema, get_db=get_db)

    if "reorder" in active:
        reorder_cfg = reorder or _from_shared(ReorderConfig, shared)
        reorder_endpoint(router, "/reorder", model, reorder_cfg, get_db=get_db)

    return router
