from __future__ import annotations

"""
OpenAPI schema tests — verify that GET and DELETE endpoints expose no request
body and no spurious query parameters when a permission_dep factory is used.
"""

from fastapi import FastAPI, APIRouter
from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Integer, String

from crudit.create.config import CreateConfig
from crudit.create.endpoint import create_endpoint
from crudit.delete.config import DeleteConfig
from crudit.delete.endpoint import delete_endpoint
from crudit.list.config import ListConfig
from crudit.list.endpoint import list_endpoint
from crudit.options.config import OptionsConfig
from crudit.options.endpoint import options_endpoint
from crudit.read.config import ReadConfig
from crudit.read.endpoint import read_endpoint
from crudit.reorder.config import ReorderConfig
from crudit.reorder.endpoint import reorder_endpoint
from crudit.update.config import UpdateConfig
from crudit.update.endpoint import update_endpoint


# ---------------------------------------------------------------------------
# Minimal ORM model + schemas for schema-generation only (no DB needed)
# ---------------------------------------------------------------------------

class _Base(DeclarativeBase):
    pass


class _Item(_Base):
    __tablename__ = "items_openapi"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    sort_order: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    _order_fields = ("name",)


class _ItemSchema(BaseModel):
    id: int
    name: str


class _ItemCreateSchema(BaseModel):
    name: str


async def _get_db():
    pass  # pragma: no cover


# ---------------------------------------------------------------------------
# permission_dep factory used in all tests
# ---------------------------------------------------------------------------

_PERMISSIONS = ["items:view", "items:edit"]


def _require(*_codes: str):
    """Minimal factory: returns a zero-param dep, simulating require_permissions."""
    async def dep() -> None:
        pass  # pragma: no cover
    return dep


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_schema(*register_fns) -> dict:
    router = APIRouter()
    for fn in register_fns:
        fn(router)
    app = FastAPI()
    app.include_router(router)
    return app.openapi()


def _op(schema: dict, method: str, path: str) -> dict:
    return schema["paths"][path][method]


def _assert_no_request_body(op: dict, label: str) -> None:
    assert "requestBody" not in op, (
        f"{label}: unexpected requestBody in OpenAPI schema"
    )


def _assert_no_perm_params(op: dict, label: str) -> None:
    params = op.get("parameters", [])
    perm_params = [p for p in params if "perm" in p["name"].lower()]
    assert not perm_params, (
        f"{label}: spurious permission-related query params: {perm_params}"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_list_no_request_body_no_perm_params():
    def register(router):
        list_endpoint(
            router, "/items", _Item, _ItemSchema,
            ListConfig(permissions=_PERMISSIONS),
            permission_dep=_require,
            get_db=_get_db,
        )

    schema = _build_schema(register)
    op = _op(schema, "get", "/items")
    _assert_no_request_body(op, "list")
    _assert_no_perm_params(op, "list")


def test_read_no_request_body_no_perm_params():
    def register(router):
        read_endpoint(
            router, "/items/{id}", _Item, _ItemSchema,
            ReadConfig(permissions=_PERMISSIONS),
            permission_dep=_require,
            get_db=_get_db,
        )

    schema = _build_schema(register)
    op = _op(schema, "get", "/items/{id}")
    _assert_no_request_body(op, "read")
    _assert_no_perm_params(op, "read")


def test_delete_no_request_body_no_perm_params():
    def register(router):
        delete_endpoint(
            router, "/items/{id}", _Item,
            DeleteConfig(permissions=_PERMISSIONS),
            permission_dep=_require,
            get_db=_get_db,
        )

    schema = _build_schema(register)
    op = _op(schema, "delete", "/items/{id}")
    _assert_no_request_body(op, "delete")
    _assert_no_perm_params(op, "delete")


def test_create_no_perm_params():
    def register(router):
        create_endpoint(
            router, "/items", _Item, _ItemCreateSchema, _ItemSchema,
            CreateConfig(permissions=_PERMISSIONS),
            permission_dep=_require,
            get_db=_get_db,
        )

    schema = _build_schema(register)
    op = _op(schema, "post", "/items")
    # POST legitimately has a requestBody — just check no perm params
    _assert_no_perm_params(op, "create")


def test_update_no_perm_params():
    def register(router):
        update_endpoint(
            router, "/items/{id}", _Item, _ItemCreateSchema, _ItemSchema,
            UpdateConfig(permissions=_PERMISSIONS),
            permission_dep=_require,
            get_db=_get_db,
        )

    schema = _build_schema(register)
    op = _op(schema, "patch", "/items/{id}")
    _assert_no_perm_params(op, "update")


def test_options_no_request_body_no_perm_params():
    def register(router):
        options_endpoint(
            router, "/items/options", _Item,
            OptionsConfig(permissions=_PERMISSIONS),
            permission_dep=_require,
            get_db=_get_db,
        )

    schema = _build_schema(register)
    op = _op(schema, "get", "/items/options")
    _assert_no_request_body(op, "options")
    _assert_no_perm_params(op, "options")


def test_reorder_no_perm_params():
    def register(router):
        reorder_endpoint(
            router, "/items/reorder", _Item,
            ReorderConfig(permissions=_PERMISSIONS),
            permission_dep=_require,
            get_db=_get_db,
        )

    schema = _build_schema(register)
    op = _op(schema, "post", "/items/reorder")
    _assert_no_perm_params(op, "reorder")


def test_no_permission_dep_no_perm_params():
    """Endpoints without a permission_dep must also have no spurious params."""
    def register(router):
        list_endpoint(
            router, "/items", _Item, _ItemSchema,
            ListConfig(),
            get_db=_get_db,
        )

    schema = _build_schema(register)
    op = _op(schema, "get", "/items")
    _assert_no_request_body(op, "list-no-dep")
    _assert_no_perm_params(op, "list-no-dep")
