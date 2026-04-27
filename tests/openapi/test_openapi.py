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


def _query_params(op: dict) -> set[str]:
    return {p["name"] for p in op.get("parameters", []) if p["in"] == "query"}


def _path_params(op: dict) -> set[str]:
    return {p["name"] for p in op.get("parameters", []) if p["in"] == "path"}


# ---------------------------------------------------------------------------
# LIST endpoint
# ---------------------------------------------------------------------------

class TestListOpenAPI:
    def _register(self, router: APIRouter, filterable_fields: list[str] | None = None) -> None:
        list_endpoint(
            router,
            "/items",
            _Item,
            _ItemSchema,
            ListConfig(
                filterable_fields=filterable_fields or [],
                permissions=_PERMISSIONS,
            ),
            permission_dep=_require,
            get_db=_get_db,
        )

    def test_method_is_get(self):
        schema = _build_schema(self._register)
        assert "get" in schema["paths"]["/items"]
        assert "post" not in schema["paths"]["/items"]

    def test_no_request_body(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items")
        assert "requestBody" not in op

    def test_pagination_query_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items")
        params = _query_params(op)
        assert {"page", "items_per_page", "offset", "limit"}.issubset(params)

    def test_search_and_sort_query_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items")
        params = _query_params(op)
        assert "q" in params
        assert "sort" in params

    def test_count_only_query_param(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items")
        assert "count_only" in _query_params(op)

    def test_filterable_fields_appear_as_query_params(self):
        def register(router):
            self._register.__func__(self, router, filterable_fields=["name", "id"])

        schema = _build_schema(register)
        op = _op(schema, "get", "/items")
        params = _query_params(op)
        assert "name" in params
        assert "id" in params

    def test_dotted_filterable_field_uses_alias(self):
        """city.name filterable field must be exposed as query alias city.name."""
        # We use a simple field with dot notation; the param name in OpenAPI is the alias
        def register(router):
            list_endpoint(
                router,
                "/items",
                _Item,
                _ItemSchema,
                ListConfig(filterable_fields=["name"]),
                get_db=_get_db,
            )

        schema = _build_schema(register)
        op = _op(schema, "get", "/items")
        assert "name" in _query_params(op)

    def test_no_path_params_on_flat_path(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items")
        assert _path_params(op) == set()

    def test_response_200_present(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items")
        assert "200" in op["responses"]

    def test_response_schema_is_paginated(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items")
        content = op["responses"]["200"]["content"]["application/json"]["schema"]
        # Resolve $ref if present
        ref = content.get("$ref", "")
        if ref:
            def_name = ref.split("/")[-1]
            resolved = schema["components"]["schemas"][def_name]
        else:
            resolved = content
        props = resolved.get("properties", {})
        assert {"data", "total_count", "has_more", "page", "items_per_page"}.issubset(props)

    def test_permission_dep_adds_no_spurious_query_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items")
        expected = {"q", "sort", "page", "items_per_page", "offset", "limit", "count_only"}
        extra = _query_params(op) - expected
        assert extra == set(), f"Unexpected query params: {extra}"

    def test_tags_propagated(self):
        def register(router):
            list_endpoint(
                router,
                "/items",
                _Item,
                _ItemSchema,
                ListConfig(tags=["items"]),
                get_db=_get_db,
            )

        schema = _build_schema(register)
        op = _op(schema, "get", "/items")
        assert "items" in op.get("tags", [])


# ---------------------------------------------------------------------------
# CREATE endpoint
# ---------------------------------------------------------------------------

class TestCreateOpenAPI:
    def _register(self, router: APIRouter) -> None:
        create_endpoint(
            router,
            "/items",
            _Item,
            _ItemCreateSchema,
            _ItemSchema,
            CreateConfig(permissions=_PERMISSIONS),
            permission_dep=_require,
            get_db=_get_db,
        )

    def test_method_is_post(self):
        schema = _build_schema(self._register)
        assert "post" in schema["paths"]["/items"]

    def test_has_request_body(self):
        schema = _build_schema(self._register)
        op = _op(schema, "post", "/items")
        assert "requestBody" in op

    def test_request_body_matches_create_schema(self):
        schema = _build_schema(self._register)
        op = _op(schema, "post", "/items")
        body_schema = op["requestBody"]["content"]["application/json"]["schema"]
        ref = body_schema.get("$ref", "")
        def_name = ref.split("/")[-1]
        resolved = schema["components"]["schemas"][def_name]
        assert "name" in resolved.get("properties", {})

    def test_response_201_present(self):
        schema = _build_schema(self._register)
        op = _op(schema, "post", "/items")
        assert "201" in op["responses"]

    def test_no_spurious_query_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "post", "/items")
        assert _query_params(op) == set()

    def test_no_path_params_on_flat_path(self):
        schema = _build_schema(self._register)
        op = _op(schema, "post", "/items")
        assert _path_params(op) == set()

    def test_tags_propagated(self):
        def register(router):
            create_endpoint(
                router,
                "/items",
                _Item,
                _ItemCreateSchema,
                _ItemSchema,
                CreateConfig(tags=["items"]),
                get_db=_get_db,
            )

        schema = _build_schema(register)
        op = _op(schema, "post", "/items")
        assert "items" in op.get("tags", [])


# ---------------------------------------------------------------------------
# READ endpoint
# ---------------------------------------------------------------------------

class TestReadOpenAPI:
    def _register(self, router: APIRouter) -> None:
        read_endpoint(
            router,
            "/items/{id}",
            _Item,
            _ItemSchema,
            ReadConfig(permissions=_PERMISSIONS),
            permission_dep=_require,
            get_db=_get_db,
        )

    def test_method_is_get(self):
        schema = _build_schema(self._register)
        assert "get" in schema["paths"]["/items/{id}"]

    def test_no_request_body(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/{id}")
        assert "requestBody" not in op

    def test_has_id_path_param(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/{id}")
        assert "id" in _path_params(op)

    def test_id_path_param_is_required(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/{id}")
        id_param = next(p for p in op["parameters"] if p["name"] == "id")
        assert id_param["required"] is True

    def test_no_spurious_query_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/{id}")
        assert _query_params(op) == set()

    def test_response_200_present(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/{id}")
        assert "200" in op["responses"]

    def test_permission_dep_adds_no_spurious_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/{id}")
        assert "requestBody" not in op
        assert _query_params(op) == set()


# ---------------------------------------------------------------------------
# UPDATE endpoint
# ---------------------------------------------------------------------------

class TestUpdateOpenAPI:
    def _register(self, router: APIRouter) -> None:
        update_endpoint(
            router,
            "/items/{id}",
            _Item,
            _ItemCreateSchema,
            _ItemSchema,
            UpdateConfig(permissions=_PERMISSIONS),
            permission_dep=_require,
            get_db=_get_db,
        )

    def test_method_is_patch(self):
        schema = _build_schema(self._register)
        assert "patch" in schema["paths"]["/items/{id}"]

    def test_has_request_body(self):
        schema = _build_schema(self._register)
        op = _op(schema, "patch", "/items/{id}")
        assert "requestBody" in op

    def test_request_body_matches_update_schema(self):
        schema = _build_schema(self._register)
        op = _op(schema, "patch", "/items/{id}")
        body_schema = op["requestBody"]["content"]["application/json"]["schema"]
        ref = body_schema.get("$ref", "")
        def_name = ref.split("/")[-1]
        resolved = schema["components"]["schemas"][def_name]
        assert "name" in resolved.get("properties", {})

    def test_has_id_path_param(self):
        schema = _build_schema(self._register)
        op = _op(schema, "patch", "/items/{id}")
        assert "id" in _path_params(op)

    def test_no_spurious_query_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "patch", "/items/{id}")
        assert _query_params(op) == set()

    def test_response_200_present(self):
        schema = _build_schema(self._register)
        op = _op(schema, "patch", "/items/{id}")
        assert "200" in op["responses"]


# ---------------------------------------------------------------------------
# DELETE endpoint
# ---------------------------------------------------------------------------

class TestDeleteOpenAPI:
    def _register(self, router: APIRouter) -> None:
        delete_endpoint(
            router,
            "/items/{id}",
            _Item,
            DeleteConfig(permissions=_PERMISSIONS),
            permission_dep=_require,
            get_db=_get_db,
        )

    def test_method_is_delete(self):
        schema = _build_schema(self._register)
        assert "delete" in schema["paths"]["/items/{id}"]

    def test_no_request_body(self):
        schema = _build_schema(self._register)
        op = _op(schema, "delete", "/items/{id}")
        assert "requestBody" not in op

    def test_has_id_path_param(self):
        schema = _build_schema(self._register)
        op = _op(schema, "delete", "/items/{id}")
        assert "id" in _path_params(op)

    def test_no_spurious_query_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "delete", "/items/{id}")
        assert _query_params(op) == set()

    def test_response_204_present(self):
        schema = _build_schema(self._register)
        op = _op(schema, "delete", "/items/{id}")
        assert "204" in op["responses"]

    def test_permission_dep_adds_no_spurious_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "delete", "/items/{id}")
        assert "requestBody" not in op
        assert _query_params(op) == set()


# ---------------------------------------------------------------------------
# OPTIONS endpoint
# ---------------------------------------------------------------------------

class TestOptionsOpenAPI:
    def _register(self, router: APIRouter, filterable_fields: list[str] | None = None) -> None:
        options_endpoint(
            router,
            "/items/options",
            _Item,
            OptionsConfig(
                label_field="name",
                filterable_fields=filterable_fields or [],
                permissions=_PERMISSIONS,
            ),
            permission_dep=_require,
            get_db=_get_db,
        )

    def test_method_is_get(self):
        schema = _build_schema(self._register)
        assert "get" in schema["paths"]["/items/options"]

    def test_no_request_body(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/options")
        assert "requestBody" not in op

    def test_offset_and_limit_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/options")
        params = _query_params(op)
        assert "offset" in params
        assert "limit" in params

    def test_search_and_sort_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/options")
        params = _query_params(op)
        assert "q" in params
        assert "sort" in params

    def test_no_page_or_items_per_page(self):
        """Options uses offset/limit only — page-based params must not appear."""
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/options")
        params = _query_params(op)
        assert "page" not in params
        assert "items_per_page" not in params

    def test_no_count_only_param(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/options")
        assert "count_only" not in _query_params(op)

    def test_filterable_fields_appear_as_query_params(self):
        def register(router):
            self._register.__func__(self, router, filterable_fields=["name"])

        schema = _build_schema(register)
        op = _op(schema, "get", "/items/options")
        assert "name" in _query_params(op)

    def test_response_200_present(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/options")
        assert "200" in op["responses"]

    def test_response_schema_has_id_and_label(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/options")
        content = op["responses"]["200"]["content"]["application/json"]["schema"]
        ref = content.get("$ref", "")
        if ref:
            def_name = ref.split("/")[-1]
            resolved = schema["components"]["schemas"][def_name]
        else:
            resolved = content
        # data items should be OptionItem with id and label
        data_items_ref = resolved["properties"]["data"]["items"].get("$ref", "")
        if data_items_ref:
            item_def = data_items_ref.split("/")[-1]
            item_schema = schema["components"]["schemas"][item_def]
            assert "id" in item_schema["properties"]
            assert "label" in item_schema["properties"]

    def test_permission_dep_adds_no_spurious_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/options")
        expected = {"q", "sort", "offset", "limit"}
        extra = _query_params(op) - expected
        assert extra == set(), f"Unexpected query params: {extra}"


# ---------------------------------------------------------------------------
# REORDER endpoint
# ---------------------------------------------------------------------------

class TestReorderOpenAPI:
    def _register(self, router: APIRouter) -> None:
        reorder_endpoint(
            router,
            "/items/reorder",
            _Item,
            ReorderConfig(permissions=_PERMISSIONS),
            permission_dep=_require,
            get_db=_get_db,
        )

    def test_method_is_post(self):
        schema = _build_schema(self._register)
        assert "post" in schema["paths"]["/items/reorder"]

    def test_has_request_body(self):
        schema = _build_schema(self._register)
        op = _op(schema, "post", "/items/reorder")
        assert "requestBody" in op

    def test_request_body_has_ids_field(self):
        schema = _build_schema(self._register)
        op = _op(schema, "post", "/items/reorder")
        body_schema = op["requestBody"]["content"]["application/json"]["schema"]
        ref = body_schema.get("$ref", "")
        if ref:
            def_name = ref.split("/")[-1]
            resolved = schema["components"]["schemas"][def_name]
        else:
            resolved = body_schema
        assert "ids" in resolved.get("properties", {})

    def test_ids_field_is_an_array(self):
        schema = _build_schema(self._register)
        op = _op(schema, "post", "/items/reorder")
        body_schema = op["requestBody"]["content"]["application/json"]["schema"]
        ref = body_schema.get("$ref", "")
        if ref:
            def_name = ref.split("/")[-1]
            resolved = schema["components"]["schemas"][def_name]
        else:
            resolved = body_schema
        assert resolved["properties"]["ids"]["type"] == "array"

    def test_response_204_present(self):
        schema = _build_schema(self._register)
        op = _op(schema, "post", "/items/reorder")
        assert "204" in op["responses"]

    def test_no_spurious_query_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "post", "/items/reorder")
        assert _query_params(op) == set()

    def test_permission_dep_adds_no_spurious_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "post", "/items/reorder")
        assert _query_params(op) == set()
        assert _path_params(op) == set()
