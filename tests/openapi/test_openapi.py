from __future__ import annotations

"""
OpenAPI schema tests — verify that GET and DELETE endpoints expose no request
body and no spurious query parameters when a permission_dep factory is used.
"""

from fastapi import FastAPI, APIRouter
from pydantic import BaseModel
from datetime import date

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import Boolean, Date, Integer, String

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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[date | None] = mapped_column(Date, nullable=True)
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


def _param_schema(op: dict, name: str) -> dict | None:
    """Return the OpenAPI schema dict for a query param by name (or alias)."""
    for p in op.get("parameters", []):
        if p.get("in") == "query" and p.get("name") == name:
            return p.get("schema", {})
    return None


def _non_null_schema(schema: dict) -> dict:
    """For anyOf-nullable schemas, return the non-null variant."""
    if "anyOf" in schema:
        non_null = [s for s in schema["anyOf"] if s.get("type") != "null"]
        return non_null[0] if non_null else schema
    return schema


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
        assert {"page", "itemsPerPage", "offset", "limit"}.issubset(params)

    def test_search_and_sort_query_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items")
        params = _query_params(op)
        assert "q" in params
        assert "sort" in params

    def test_count_only_query_param(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items")
        assert "countOnly" in _query_params(op)

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
        assert {"data", "totalCount", "hasMore", "page", "itemsPerPage"}.issubset(props)

    def test_permission_dep_adds_no_spurious_query_params(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items")
        expected = {"q", "sort", "page", "itemsPerPage", "offset", "limit", "countOnly"}
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

    def test_string_filter_has_string_type(self):
        def register(router):
            list_endpoint(router, "/items", _Item, _ItemSchema, ListConfig(filterable_fields=["name"]), get_db=_get_db)

        schema = _build_schema(register)
        op = _op(schema, "get", "/items")
        s = _non_null_schema(_param_schema(op, "name"))
        assert s.get("type") == "array"
        assert s.get("items", {}).get("type") == "string"

    def test_integer_filter_has_integer_type(self):
        def register(router):
            list_endpoint(router, "/items", _Item, _ItemSchema, ListConfig(filterable_fields=["id"]), get_db=_get_db)

        schema = _build_schema(register)
        op = _op(schema, "get", "/items")
        s = _non_null_schema(_param_schema(op, "id"))
        assert s.get("type") == "array"
        assert s.get("items", {}).get("type") == "integer"

    def test_string_filter_operator_params_appear(self):
        def register(router):
            list_endpoint(router, "/items", _Item, _ItemSchema, ListConfig(filterable_fields=["name"]), get_db=_get_db)

        schema = _build_schema(register)
        op = _op(schema, "get", "/items")
        params = _query_params(op)
        assert "name__ilike" in params
        assert "name__like" in params
        assert "name__ne" in params
        assert "name__isnull" in params

    def test_integer_filter_operator_params_appear(self):
        def register(router):
            list_endpoint(router, "/items", _Item, _ItemSchema, ListConfig(filterable_fields=["id"]), get_db=_get_db)

        schema = _build_schema(register)
        op = _op(schema, "get", "/items")
        params = _query_params(op)
        assert "id__gte" in params
        assert "id__lte" in params
        assert "id__gt" in params
        assert "id__lt" in params
        assert "id__ne" in params
        assert "id__isnull" in params

    def test_integer_operator_params_have_integer_type(self):
        def register(router):
            list_endpoint(router, "/items", _Item, _ItemSchema, ListConfig(filterable_fields=["id"]), get_db=_get_db)

        schema = _build_schema(register)
        op = _op(schema, "get", "/items")
        assert _non_null_schema(_param_schema(op, "id__gte")).get("type") == "integer"
        assert _non_null_schema(_param_schema(op, "id__lt")).get("type") == "integer"

    def test_isnull_param_has_boolean_type(self):
        def register(router):
            list_endpoint(router, "/items", _Item, _ItemSchema, ListConfig(filterable_fields=["name"]), get_db=_get_db)

        schema = _build_schema(register)
        op = _op(schema, "get", "/items")
        s = _non_null_schema(_param_schema(op, "name__isnull"))
        assert s.get("type") == "boolean"

    def test_date_filter_operator_params_appear(self):
        def register(router):
            list_endpoint(router, "/items", _Item, _ItemSchema, ListConfig(filterable_fields=["created_at"]), get_db=_get_db)

        schema = _build_schema(register)
        op = _op(schema, "get", "/items")
        params = _query_params(op)
        assert "created_at__gte" in params
        assert "created_at__lte" in params
        assert "created_at__year" in params
        assert "created_at__quarter" in params
        assert "created_at__month" in params
        assert "created_at__week" in params
        assert "created_at__relative" in params

    def test_date_year_param_has_integer_type(self):
        def register(router):
            list_endpoint(router, "/items", _Item, _ItemSchema, ListConfig(filterable_fields=["created_at"]), get_db=_get_db)

        schema = _build_schema(register)
        op = _op(schema, "get", "/items")
        assert _non_null_schema(_param_schema(op, "created_at__year")).get("type") == "integer"


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
        assert "itemsPerPage" not in params

    def test_no_count_only_param(self):
        schema = _build_schema(self._register)
        op = _op(schema, "get", "/items/options")
        assert "countOnly" not in _query_params(op)

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


# ---------------------------------------------------------------------------
# path_filters — LIST and OPTIONS endpoints
# ---------------------------------------------------------------------------

class TestPathFiltersOpenAPI:
    """path_filters maps URL path params onto model fields. The path params
    must appear as required path parameters in the OpenAPI schema and must
    not leak into the query parameters."""

    def _register_list(self, router: APIRouter) -> None:
        list_endpoint(
            router,
            "/cities/{city_id}/items",
            _Item,
            _ItemSchema,
            ListConfig(
                filterable_fields=["name"],
                permissions=_PERMISSIONS,
            ),
            path_filters={"city_id": "id"},
            permission_dep=_require,
            get_db=_get_db,
        )

    def _register_options(self, router: APIRouter) -> None:
        options_endpoint(
            router,
            "/cities/{city_id}/items/options",
            _Item,
            OptionsConfig(
                label_field="name",
                filterable_fields=["name"],
                permissions=_PERMISSIONS,
            ),
            path_filters={"city_id": "id"},
            permission_dep=_require,
            get_db=_get_db,
        )

    # -- list --------------------------------------------------------------

    def test_list_path_param_appears(self):
        schema = _build_schema(self._register_list)
        op = _op(schema, "get", "/cities/{city_id}/items")
        assert "city_id" in _path_params(op)

    def test_list_path_param_is_required(self):
        schema = _build_schema(self._register_list)
        op = _op(schema, "get", "/cities/{city_id}/items")
        param = next(p for p in op["parameters"] if p["name"] == "city_id")
        assert param["in"] == "path"
        assert param["required"] is True

    def test_list_path_param_not_in_query(self):
        schema = _build_schema(self._register_list)
        op = _op(schema, "get", "/cities/{city_id}/items")
        assert "city_id" not in _query_params(op)

    def test_list_path_filter_does_not_suppress_other_params(self):
        """Adding a path filter must not strip the standard list query params."""
        schema = _build_schema(self._register_list)
        op = _op(schema, "get", "/cities/{city_id}/items")
        params = _query_params(op)
        assert {"page", "itemsPerPage", "offset", "limit", "q", "sort", "countOnly"}.issubset(params)
        assert "name" in params  # filterable field still exposed

    def test_list_multiple_path_filters_all_appear(self):
        """When several path params are mapped, each one must appear in the schema."""
        def register(router):
            list_endpoint(
                router,
                "/companies/{company_id}/cities/{city_id}/items",
                _Item,
                _ItemSchema,
                ListConfig(),
                path_filters={"company_id": "id", "city_id": "id"},
                get_db=_get_db,
            )

        schema = _build_schema(register)
        op = _op(schema, "get", "/companies/{company_id}/cities/{city_id}/items")
        path_params = _path_params(op)
        assert {"company_id", "city_id"}.issubset(path_params)
        query_params = _query_params(op)
        assert "company_id" not in query_params
        assert "city_id" not in query_params

    # -- options -----------------------------------------------------------

    def test_options_path_param_appears(self):
        schema = _build_schema(self._register_options)
        op = _op(schema, "get", "/cities/{city_id}/items/options")
        assert "city_id" in _path_params(op)

    def test_options_path_param_is_required(self):
        schema = _build_schema(self._register_options)
        op = _op(schema, "get", "/cities/{city_id}/items/options")
        param = next(p for p in op["parameters"] if p["name"] == "city_id")
        assert param["in"] == "path"
        assert param["required"] is True

    def test_options_path_param_not_in_query(self):
        schema = _build_schema(self._register_options)
        op = _op(schema, "get", "/cities/{city_id}/items/options")
        assert "city_id" not in _query_params(op)

    def test_options_path_filter_does_not_suppress_other_params(self):
        schema = _build_schema(self._register_options)
        op = _op(schema, "get", "/cities/{city_id}/items/options")
        params = _query_params(op)
        assert {"q", "sort", "offset", "limit"}.issubset(params)
        assert "name" in params  # filterable field still exposed

    # -- create ------------------------------------------------------------

    def _register_create(self, router: APIRouter, create_schema: type[BaseModel]) -> None:
        create_endpoint(
            router,
            "/cities/{city_id}/items",
            _Item,
            create_schema,
            _ItemSchema,
            CreateConfig(permissions=_PERMISSIONS),
            path_filters={"city_id": "id"},
            permission_dep=_require,
            get_db=_get_db,
        )

    def test_create_path_param_appears(self):
        def register(router):
            self._register_create(router, _ItemCreateSchema)

        schema = _build_schema(register)
        op = _op(schema, "post", "/cities/{city_id}/items")
        assert "city_id" in _path_params(op)
        param = next(p for p in op["parameters"] if p["name"] == "city_id")
        assert param["required"] is True

    def test_create_path_param_not_in_query(self):
        def register(router):
            self._register_create(router, _ItemCreateSchema)

        schema = _build_schema(register)
        op = _op(schema, "post", "/cities/{city_id}/items")
        assert "city_id" not in _query_params(op)

    def test_create_body_schema_excludes_path_filter_field(self):
        """When a create schema declares the path-filter field, the OpenAPI
        request body must drop it (the URL provides the value)."""

        class _ItemCreateWithId(BaseModel):
            name: str
            id: int  # would normally be the model field set by path_filters

        def register(router):
            self._register_create(router, _ItemCreateWithId)

        schema = _build_schema(register)
        op = _op(schema, "post", "/cities/{city_id}/items")
        body_ref = op["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        body_def = schema["components"]["schemas"][body_ref.split("/")[-1]]
        properties = body_def.get("properties", {})
        assert "name" in properties
        assert "id" not in properties
        assert "id" not in body_def.get("required", [])

    def test_create_body_schema_unchanged_when_field_absent(self):
        """If the create schema does not declare the path-filter field, the
        body schema is left alone."""
        def register(router):
            self._register_create(router, _ItemCreateSchema)

        schema = _build_schema(register)
        op = _op(schema, "post", "/cities/{city_id}/items")
        body_ref = op["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        body_def = schema["components"]["schemas"][body_ref.split("/")[-1]]
        assert "name" in body_def["properties"]

    # -- reorder -----------------------------------------------------------

    def _register_reorder(self, router: APIRouter) -> None:
        reorder_endpoint(
            router,
            "/cities/{city_id}/items/reorder",
            _Item,
            ReorderConfig(permissions=_PERMISSIONS),
            path_filters={"city_id": "id"},
            permission_dep=_require,
            get_db=_get_db,
        )

    def test_reorder_path_param_appears(self):
        schema = _build_schema(self._register_reorder)
        op = _op(schema, "post", "/cities/{city_id}/items/reorder")
        assert "city_id" in _path_params(op)
        param = next(p for p in op["parameters"] if p["name"] == "city_id")
        assert param["required"] is True

    def test_reorder_path_param_not_in_query(self):
        schema = _build_schema(self._register_reorder)
        op = _op(schema, "post", "/cities/{city_id}/items/reorder")
        assert "city_id" not in _query_params(op)


# ---------------------------------------------------------------------------
# 401 response — declared whenever login_dep is provided
# ---------------------------------------------------------------------------


async def _login_dep() -> None:
    pass  # pragma: no cover


def _routes_with_login(register_with_login: bool):
    """Register every endpoint with or without login_dep and return its op dict."""
    login = _login_dep if register_with_login else None

    def register(router):
        list_endpoint(
            router,
            "/items",
            _Item,
            _ItemSchema,
            ListConfig(),
            login_dep=login,
            get_db=_get_db,
        )
        read_endpoint(
            router,
            "/items/{id}",
            _Item,
            _ItemSchema,
            ReadConfig(),
            login_dep=login,
            get_db=_get_db,
        )
        create_endpoint(
            router,
            "/items",
            _Item,
            _ItemCreateSchema,
            _ItemSchema,
            CreateConfig(),
            login_dep=login,
            get_db=_get_db,
        )
        update_endpoint(
            router,
            "/items/{id}",
            _Item,
            _ItemCreateSchema,
            _ItemSchema,
            UpdateConfig(),
            login_dep=login,
            get_db=_get_db,
        )
        delete_endpoint(
            router,
            "/items/{id}",
            _Item,
            DeleteConfig(),
            login_dep=login,
            get_db=_get_db,
        )
        options_endpoint(
            router,
            "/items/options",
            _Item,
            OptionsConfig(label_field="name"),
            login_dep=login,
            get_db=_get_db,
        )
        reorder_endpoint(
            router,
            "/items/reorder",
            _Item,
            ReorderConfig(),
            login_dep=login,
            get_db=_get_db,
        )

    return _build_schema(register)


_OPS = [
    ("get", "/items"),
    ("get", "/items/{id}"),
    ("post", "/items"),
    ("patch", "/items/{id}"),
    ("delete", "/items/{id}"),
    ("get", "/items/options"),
    ("post", "/items/reorder"),
]


class TestLogin401Response:
    """When login_dep is supplied, every endpoint must declare a 401 response;
    when login_dep is omitted, 401 must not appear (the dep cannot raise it)."""

    def test_401_present_on_each_endpoint_when_login_dep_set(self):
        schema = _routes_with_login(register_with_login=True)
        for method, path in _OPS:
            op = _op(schema, method, path)
            assert "401" in op["responses"], f"{method.upper()} {path} missing 401"

    def test_401_absent_on_each_endpoint_when_no_login_dep(self):
        schema = _routes_with_login(register_with_login=False)
        for method, path in _OPS:
            op = _op(schema, method, path)
            assert "401" not in op["responses"], (
                f"{method.upper()} {path} unexpectedly declares 401 without login_dep"
            )

    def test_401_description_is_unauthorized(self):
        schema = _routes_with_login(register_with_login=True)
        for method, path in _OPS:
            op = _op(schema, method, path)
            assert op["responses"]["401"]["description"] == "Unauthorized"


# ---------------------------------------------------------------------------
# 401 response — crud_router propagation
# ---------------------------------------------------------------------------


class TestCrudRouter401Response:
    """crud_router forwards login_dep to every endpoint factory; 401 should
    surface on every registered route when login_dep is set."""

    def _build(self, *, with_login: bool) -> dict:
        from crudit.router import crud_router

        login = _login_dep if with_login else None
        router = crud_router(
            model=_Item,
            list_item_schema=_ItemSchema,
            read_schema=_ItemSchema,
            create_schema=_ItemCreateSchema,
            update_schema=_ItemCreateSchema,
            get_db=_get_db,
            login_dep=login,
            extra_endpoints=["options", "reorder"],
        )
        app = FastAPI()
        app.include_router(router, prefix="/items")
        return app.openapi()

    def test_crud_router_declares_401_when_login_dep_set(self):
        schema = self._build(with_login=True)
        for method, path in [
            ("get", "/items"),
            ("post", "/items"),
            ("get", "/items/options"),
            ("post", "/items/reorder"),
            ("get", "/items/{id}"),
            ("patch", "/items/{id}"),
            ("delete", "/items/{id}"),
        ]:
            op = _op(schema, method, path)
            assert "401" in op["responses"], f"{method.upper()} {path} missing 401"

    def test_crud_router_omits_401_when_no_login_dep(self):
        schema = self._build(with_login=False)
        for method, path in [
            ("get", "/items"),
            ("post", "/items"),
            ("get", "/items/options"),
            ("post", "/items/reorder"),
            ("get", "/items/{id}"),
            ("patch", "/items/{id}"),
            ("delete", "/items/{id}"),
        ]:
            op = _op(schema, method, path)
            assert "401" not in op["responses"], (
                f"{method.upper()} {path} unexpectedly declares 401 without login_dep"
            )


# ---------------------------------------------------------------------------
# 401 response — m2m_router
# ---------------------------------------------------------------------------


class TestM2M401Response:
    """The m2m endpoints (list/add/remove) declare 401 only when both
    login_required is True and login_dep is provided."""

    def _build(self, *, login_dep, login_required: bool) -> dict:
        from sqlalchemy import Column, ForeignKey, Integer, Table

        from crudit.m2m.config import M2MConfig
        from crudit.m2m.endpoint import m2m_router

        class _Base2(DeclarativeBase):
            pass

        class _Parent(_Base2):
            __tablename__ = "m2m_parent"
            id: Mapped[int] = mapped_column(Integer, primary_key=True)

        class _Child(_Base2):
            __tablename__ = "m2m_child"
            id: Mapped[int] = mapped_column(Integer, primary_key=True)

        assoc = Table(
            "m2m_assoc",
            _Base2.metadata,
            Column("parent_id", Integer, ForeignKey("m2m_parent.id"), primary_key=True),
            Column("child_id", Integer, ForeignKey("m2m_child.id"), primary_key=True),
        )

        class _ChildSchema(BaseModel):
            id: int

        router = m2m_router(
            parent_model=_Parent,
            child_model=_Child,
            association_table=assoc,
            child_schema=_ChildSchema,
            prefix="/parents",
            get_db=_get_db,
            config=M2MConfig(login_required=login_required),
            login_dep=login_dep,
        )
        app = FastAPI()
        app.include_router(router)
        return app.openapi()

    def test_m2m_declares_401_when_login_dep_and_login_required(self):
        schema = self._build(login_dep=_login_dep, login_required=True)
        path = "/parents/{parent_id}/_childs"
        for method in ("get", "post", "delete"):
            op = _op(schema, method, path)
            assert "401" in op["responses"], f"{method.upper()} {path} missing 401"

    def test_m2m_omits_401_when_no_login_dep(self):
        schema = self._build(login_dep=None, login_required=True)
        path = "/parents/{parent_id}/_childs"
        for method in ("get", "post", "delete"):
            op = _op(schema, method, path)
            assert "401" not in op["responses"]

    def test_m2m_omits_401_when_login_not_required(self):
        schema = self._build(login_dep=_login_dep, login_required=False)
        path = "/parents/{parent_id}/_childs"
        for method in ("get", "post", "delete"):
            op = _op(schema, method, path)
            assert "401" not in op["responses"]


# ---------------------------------------------------------------------------
# operation_id — auto-generated from verb + model name, overridable
# ---------------------------------------------------------------------------


class TestOperationIdDefaults:
    """Each endpoint derives a sensible default operation_id from the model name."""

    def test_list_default_operation_id(self):
        def register(router):
            list_endpoint(router, "/items", _Item, _ItemSchema, ListConfig(), get_db=_get_db)

        schema = _build_schema(register)
        assert _op(schema, "get", "/items")["operationId"] == "list_item"

    def test_read_default_operation_id(self):
        def register(router):
            read_endpoint(router, "/items/{id}", _Item, _ItemSchema, ReadConfig(), get_db=_get_db)

        schema = _build_schema(register)
        assert _op(schema, "get", "/items/{id}")["operationId"] == "read_item"

    def test_create_default_operation_id(self):
        def register(router):
            create_endpoint(
                router, "/items", _Item, _ItemCreateSchema, _ItemSchema,
                CreateConfig(), get_db=_get_db,
            )

        schema = _build_schema(register)
        assert _op(schema, "post", "/items")["operationId"] == "create_item"

    def test_update_default_operation_id(self):
        def register(router):
            update_endpoint(
                router, "/items/{id}", _Item, _ItemCreateSchema, _ItemSchema,
                UpdateConfig(), get_db=_get_db,
            )

        schema = _build_schema(register)
        assert _op(schema, "patch", "/items/{id}")["operationId"] == "update_item"

    def test_delete_default_operation_id(self):
        def register(router):
            delete_endpoint(router, "/items/{id}", _Item, DeleteConfig(), get_db=_get_db)

        schema = _build_schema(register)
        assert _op(schema, "delete", "/items/{id}")["operationId"] == "delete_item"

    def test_options_default_operation_id(self):
        def register(router):
            options_endpoint(
                router, "/items/options", _Item,
                OptionsConfig(label_field="name"), get_db=_get_db,
            )

        schema = _build_schema(register)
        assert _op(schema, "get", "/items/options")["operationId"] == "list_item_options"

    def test_reorder_default_operation_id(self):
        def register(router):
            reorder_endpoint(router, "/items/reorder", _Item, ReorderConfig(), get_db=_get_db)

        schema = _build_schema(register)
        assert _op(schema, "post", "/items/reorder")["operationId"] == "reorder_item"

    def test_camelcase_model_name_is_snake_cased(self):
        """A multi-word model class name like ``CompanyUser`` becomes ``company_user``."""

        class CompanyUser(_Base):
            __tablename__ = "company_users_op_id"
            id: Mapped[int] = mapped_column(Integer, primary_key=True)
            name: Mapped[str] = mapped_column(String)

        class _CompanyUserSchema(BaseModel):
            id: int
            name: str

        def register(router):
            list_endpoint(router, "/cus", CompanyUser, _CompanyUserSchema, ListConfig(), get_db=_get_db)

        schema = _build_schema(register)
        assert _op(schema, "get", "/cus")["operationId"] == "list_company_user"


class TestOperationIdOverride:
    """The operation_id can be overridden either via the keyword arg or via the config."""

    def test_kwarg_override_wins_over_default(self):
        def register(router):
            list_endpoint(
                router, "/items", _Item, _ItemSchema, ListConfig(),
                operation_id="custom_list_items", get_db=_get_db,
            )

        schema = _build_schema(register)
        assert _op(schema, "get", "/items")["operationId"] == "custom_list_items"

    def test_config_field_override_wins_over_default(self):
        def register(router):
            list_endpoint(
                router, "/items", _Item, _ItemSchema,
                ListConfig(operation_id="from_config"), get_db=_get_db,
            )

        schema = _build_schema(register)
        assert _op(schema, "get", "/items")["operationId"] == "from_config"

    def test_kwarg_takes_precedence_over_config(self):
        def register(router):
            list_endpoint(
                router, "/items", _Item, _ItemSchema,
                ListConfig(operation_id="from_config"),
                operation_id="from_kwarg",
                get_db=_get_db,
            )

        schema = _build_schema(register)
        assert _op(schema, "get", "/items")["operationId"] == "from_kwarg"


class TestM2MOperationId:
    """m2m endpoints derive list/add/remove operation_ids from parent + child names."""

    def _build(self, *, config_kwargs: dict | None = None) -> dict:
        from sqlalchemy import Column, ForeignKey, Integer, Table

        from crudit.m2m.config import M2MConfig
        from crudit.m2m.endpoint import m2m_router

        class _Base3(DeclarativeBase):
            pass

        class _User(_Base3):
            __tablename__ = "m2m_op_user"
            id: Mapped[int] = mapped_column(Integer, primary_key=True)

        class _Permission(_Base3):
            __tablename__ = "m2m_op_perm"
            id: Mapped[int] = mapped_column(Integer, primary_key=True)

        assoc = Table(
            "m2m_op_assoc",
            _Base3.metadata,
            Column("user_id", Integer, ForeignKey("m2m_op_user.id"), primary_key=True),
            Column("permission_id", Integer, ForeignKey("m2m_op_perm.id"), primary_key=True),
        )

        class _PermSchema(BaseModel):
            id: int

        router = m2m_router(
            parent_model=_User,
            child_model=_Permission,
            association_table=assoc,
            child_schema=_PermSchema,
            prefix="/users",
            get_db=_get_db,
            config=M2MConfig(**(config_kwargs or {})),
        )
        app = FastAPI()
        app.include_router(router)
        return app.openapi()

    def test_default_list_add_remove_operation_ids(self):
        schema = self._build()
        path = "/users/{user_id}/_permissions"
        assert _op(schema, "get", path)["operationId"] == "list_user_permission"
        assert _op(schema, "post", path)["operationId"] == "add_user_permission"
        assert _op(schema, "delete", path)["operationId"] == "remove_user_permission"

    def test_overrides_apply(self):
        schema = self._build(config_kwargs={
            "list_operation_id": "my_list",
            "add_operation_id": "my_add",
            "remove_operation_id": "my_remove",
        })
        path = "/users/{user_id}/_permissions"
        assert _op(schema, "get", path)["operationId"] == "my_list"
        assert _op(schema, "post", path)["operationId"] == "my_add"
        assert _op(schema, "delete", path)["operationId"] == "my_remove"
