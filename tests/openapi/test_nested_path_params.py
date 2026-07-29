from __future__ import annotations

"""
OpenAPI schema tests for the path parameters of nested routes.

FastAPI only documents path params that appear in the endpoint signature, so a
placeholder that no handler declares is missing from the schema even though the
URL cannot be built without it. Two mechanisms fill that in:

* ``path_filters`` — forwarded to every verb, including the ``/{id}`` ones.
* ``include_nested_router`` — declares the ancestor ids carried by a mount prefix.
"""

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel
from sqlalchemy import Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from crudit.mount import include_nested_router
from crudit.router import crud_router


class _Base(DeclarativeBase):
    pass


class _District(_Base):
    __tablename__ = "districts_nested"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String)


class _DistrictSchema(BaseModel):
    id: int
    name: str


class _DistrictWriteSchema(BaseModel):
    name: str


async def _get_db():
    pass  # pragma: no cover


def _districts_router() -> APIRouter:
    return crud_router(
        model=_District,
        list_item_schema=_DistrictSchema,
        read_schema=_DistrictSchema,
        create_schema=_DistrictWriteSchema,
        update_schema=_DistrictWriteSchema,
        get_db=_get_db,
        crud_endpoints=["list", "read", "create", "update", "delete"],
        path_filters={"city_id": "city_id"},
        mcp_expose=False,
    )


def _path_params(schema: dict, method: str, path: str) -> set[str]:
    op = schema["paths"][path][method]
    return {p["name"] for p in op.get("parameters", []) if p["in"] == "path"}


def _param_type(schema: dict, method: str, path: str, name: str) -> str | None:
    op = schema["paths"][path][method]
    for p in op.get("parameters", []):
        if p["in"] == "path" and p["name"] == name:
            return p["schema"].get("type")
    return None  # pragma: no cover


class TestPathFiltersOnDetailRoutes:
    """``path_filters`` reaches read/update/delete, not just list/create."""

    def _schema(self) -> dict:
        app = FastAPI()
        app.include_router(_districts_router(), prefix="/cities/{city_id}/districts")
        return app.openapi()

    def test_collection_routes_declare_the_parent(self):
        schema = self._schema()
        for method in ("get", "post"):
            assert _path_params(schema, method, "/cities/{city_id}/districts") == {"city_id"}

    def test_detail_routes_declare_the_parent_and_the_id(self):
        schema = self._schema()
        path = "/cities/{city_id}/districts/{id}"
        for method in ("get", "patch", "delete"):
            assert _path_params(schema, method, path) == {"city_id", "id"}

    def test_parent_param_is_typed_from_the_model_column(self):
        schema = self._schema()
        path = "/cities/{city_id}/districts/{id}"
        assert _param_type(schema, "get", path, "city_id") == "integer"


class TestIncludeNestedRouter:
    """Placeholders that only exist in the mount prefix still get declared."""

    def _schema(self, prefix: str, **kwargs) -> dict:
        app = FastAPI()
        router = APIRouter()
        include_nested_router(router, _districts_router(), prefix=prefix, **kwargs)
        app.include_router(router)
        return app.openapi()

    def test_ancestor_id_absent_from_path_filters_is_declared(self):
        # `region_id` maps onto no column of _District — it is pure URL context.
        prefix = "/regions/{region_id}/cities/{city_id}/districts"
        schema = self._schema(prefix)
        assert _path_params(schema, "get", prefix) == {"region_id", "city_id"}
        assert _path_params(schema, "get", f"{prefix}/{{id}}") == {"region_id", "city_id", "id"}

    def test_inferred_ancestor_type_is_integer_for_id_suffixed_names(self):
        prefix = "/regions/{region_id}/cities/{city_id}/districts"
        schema = self._schema(prefix)
        assert _param_type(schema, "get", prefix, "region_id") == "integer"

    def test_non_id_placeholder_defaults_to_string(self):
        prefix = "/{scope}/cities/{city_id}/districts"
        schema = self._schema(prefix)
        assert _param_type(schema, "get", prefix, "scope") == "string"

    def test_param_types_override_the_inference(self):
        prefix = "/{scope}/cities/{city_id}/districts"
        schema = self._schema(prefix, param_types={"scope": int})
        assert _param_type(schema, "get", prefix, "scope") == "integer"

    def test_a_declared_param_keeps_its_own_annotation(self):
        # `city_id` comes from path_filters, so the helper must not redeclare it.
        prefix = "/regions/{region_id}/cities/{city_id}/districts"
        schema = self._schema(prefix)
        op = schema["paths"][prefix]["get"]
        assert len([p for p in op["parameters"] if p["name"] == "city_id"]) == 1

    def test_prefix_without_placeholders_adds_nothing(self):
        # Only what `path_filters` already declared — the helper contributes no
        # params of its own when the prefix carries no placeholder.
        schema = self._schema("/districts")
        assert _path_params(schema, "get", "/districts") == {"city_id"}
        assert _path_params(schema, "get", "/districts/{id}") == {"city_id", "id"}
