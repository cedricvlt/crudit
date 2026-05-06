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
from crudit.types import PermissionDepFn
from crudit.update.config import UpdateConfig
from crudit.update.endpoint import update_endpoint

_CRUD_ENDPOINTS = ["list", "read", "create", "update", "delete"]
_EXTRA_ENDPOINTS = ["options", "reorder"]


@dataclass
class SharedConfig:
    """Auth/FastAPI defaults applied to any verb that has no explicit per-verb config."""

    permissions: list[str] = field(default_factory=list)
    login_required: bool = True
    dependencies: list[Any] = field(default_factory=list)


def _from_shared(
    config_cls: type,
    shared: SharedConfig | None,
    *,
    tags: list[str],
    **extra: Any,
) -> Any:
    if shared is None:
        return config_cls(tags=tags, **extra)
    return config_cls(
        permissions=shared.permissions,
        login_required=shared.login_required,
        dependencies=shared.dependencies,
        tags=tags,
        **extra,
    )


def crud_router(
    model: type[DeclarativeBase],
    *,
    list_item_schema: type[BaseModel] | None = None,
    read_schema: type[BaseModel] | None = None,
    create_schema: type[BaseModel] | None = None,
    update_schema: type[BaseModel] | None = None,
    option_schema: type[BaseModel] | None = None,
    get_db: Callable,
    login_dep: Callable | None = None,
    permission_dep: PermissionDepFn | None = None,
    tags: list[str] | None = None,
    crud_endpoints: list[str] | None = None,
    extra_endpoints: list[str] | None = None,
    path_filters: dict[str, str] | None = None,
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

    Defaults to list, read, create, update, delete. Pass `crud_endpoints` to restrict
    which core verbs are registered. Pass `extra_endpoints` to opt in to options/reorder.

    `shared` provides default auth/FastAPI fields for any verb without an explicit
    per-verb config. When a per-verb config is given it is used as-is.

    `path_filters` maps URL path params onto model fields. It is forwarded to
    list, options, reorder, and create endpoints (the verbs that operate on
    collections or write a new row). For nested resources such as
    ``/cities/{city_id}/districts`` set ``path_filters={"city_id": "city_id"}``.

    Schema routing:
      list    → list_item_schema
      read    → read_schema
      create  → create_schema (input) + read_schema (output)
      update  → update_schema (input) + read_schema (output)
      options → option_schema for join resolution (output is always OptionItem)
      reorder → no schema
    """
    active_crud = set(crud_endpoints if crud_endpoints is not None else _CRUD_ENDPOINTS)
    active_extra = set(extra_endpoints or [])
    active = active_crud | active_extra

    unknown_crud = active_crud - set(_CRUD_ENDPOINTS)
    if unknown_crud:
        raise CruditConfigError(
            f"Unknown crud_endpoint name(s): {sorted(unknown_crud)}. Valid: {_CRUD_ENDPOINTS}"
        )
    unknown_extra = active_extra - set(_EXTRA_ENDPOINTS)
    if unknown_extra:
        raise CruditConfigError(
            f"Unknown extra_endpoint name(s): {sorted(unknown_extra)}. Valid: {_EXTRA_ENDPOINTS}"
        )

    if "list" in active and list_item_schema is None:
        raise CruditConfigError("list_item_schema is required when 'list' is in crud_endpoints.")
    if "read" in active and read_schema is None:
        raise CruditConfigError("read_schema is required when 'read' is in crud_endpoints.")
    if "create" in active:
        if create_schema is None:
            raise CruditConfigError("create_schema is required when 'create' is in crud_endpoints.")
        if read_schema is None:
            raise CruditConfigError("read_schema is required when 'create' is in crud_endpoints.")
    if "update" in active:
        if update_schema is None:
            raise CruditConfigError("update_schema is required when 'update' is in crud_endpoints.")
        if read_schema is None:
            raise CruditConfigError("read_schema is required when 'update' is in crud_endpoints.")

    _tags = tags or []
    _shared_kwargs = dict(tags=_tags)
    _endpoint_kwargs = dict(login_dep=login_dep, permission_dep=permission_dep, get_db=get_db)
    _path_filter_kwargs = dict(path_filters=path_filters) if path_filters else {}

    router = APIRouter()

    if "list" in active:
        list_cfg = list or _from_shared(ListConfig, shared, **_shared_kwargs)
        list_endpoint(router, "", model, list_item_schema, list_cfg, **_path_filter_kwargs, **_endpoint_kwargs)

    if "create" in active:
        create_cfg = create or _from_shared(CreateConfig, shared, **_shared_kwargs)
        create_endpoint(router, "", model, create_schema, read_schema, create_cfg, **_path_filter_kwargs, **_endpoint_kwargs)

    if "options" in active:
        options_cfg = options or _from_shared(OptionsConfig, shared, **_shared_kwargs)
        _opt_schema_kwargs = {"schema": option_schema} if option_schema is not None else {}
        options_endpoint(router, "/options", model, options_cfg, **_opt_schema_kwargs, **_path_filter_kwargs, **_endpoint_kwargs)

    if "reorder" in active:
        reorder_cfg = reorder or _from_shared(ReorderConfig, shared, **_shared_kwargs)
        reorder_endpoint(router, "/reorder", model, reorder_cfg, **_path_filter_kwargs, **_endpoint_kwargs)

    if "read" in active:
        read_cfg = read or _from_shared(ReadConfig, shared, **_shared_kwargs)
        read_endpoint(router, "/{id}", model, read_schema, read_cfg, **_endpoint_kwargs)

    if "update" in active:
        update_cfg = update or _from_shared(UpdateConfig, shared, **_shared_kwargs)
        update_endpoint(router, "/{id}", model, update_schema, read_schema, update_cfg, **_endpoint_kwargs)

    if "delete" in active:
        delete_cfg = delete or _from_shared(DeleteConfig, shared, **_shared_kwargs)
        delete_endpoint(router, "/{id}", model, delete_cfg, **_endpoint_kwargs)

    return router
