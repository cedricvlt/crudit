"""Tests for the crud_router/m2m_router declaration registry."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from crudit import (
    CreateConfig,
    CruditConfigError,
    ListConfig,
    crud_router,
    m2m_router,
)
from crudit.registry import iter_cruds, iter_m2ms, reset
from tests.conftest import City, District, User, district_allowed_users


class DistrictListSchema(BaseModel):
    id: int
    name: str


class DistrictReadSchema(BaseModel):
    id: int
    name: str


class DistrictCreateSchema(BaseModel):
    name: str
    city_id: int


class DistrictUpdateSchema(BaseModel):
    name: str | None = None


class LeanSchema(BaseModel):
    id: int


async def fake_get_db():
    yield None


def _make_router(**kwargs):
    return crud_router(
        District,
        list_item_schema=DistrictListSchema,
        read_schema=DistrictReadSchema,
        create_schema=DistrictCreateSchema,
        update_schema=DistrictUpdateSchema,
        get_db=fake_get_db,
        **kwargs,
    )


def test_crud_router_registers_declaration():
    _make_router()
    decls = iter_cruds()
    assert len(decls) == 1
    d = decls[0]
    # tests.conftest has no domain segment → bare snake model name
    assert d.entity_type == "district"
    assert d.model is District
    assert d.read_schema is DistrictReadSchema
    assert d.create_schema is DistrictCreateSchema
    assert d.update_schema is DistrictUpdateSchema
    assert d.list_config is not None
    assert d.create_config is not None
    assert d.delete_config is not None


def test_crud_router_entity_type_and_description_overrides():
    _make_router(
        mcp_entity_type="core.district",
        mcp_description="Districts of a city.",
        mcp_read_schema=LeanSchema,
    )
    d = iter_cruds()[0]
    assert d.entity_type == "core.district"
    assert d.description == "Districts of a city."
    assert d.mcp_read_schema is LeanSchema


def test_crud_router_mcp_expose_false():
    _make_router(mcp_expose=False)
    assert iter_cruds() == ()


def test_crud_router_mcp_exclude_validation():
    with pytest.raises(CruditConfigError, match="mcp_exclude"):
        _make_router(mcp_exclude=["nonsense"])


def test_crud_router_mcp_exclude_recorded():
    _make_router(mcp_exclude=["delete"])
    assert iter_cruds()[0].mcp_exclude == frozenset({"delete"})


def test_crud_router_inactive_verbs_have_no_config():
    crud_router(
        District,
        list_item_schema=DistrictListSchema,
        read_schema=DistrictReadSchema,
        get_db=fake_get_db,
        crud_endpoints=["list", "read"],
    )
    d = iter_cruds()[0]
    assert d.create_config is None
    assert d.update_config is None
    assert d.delete_config is None
    assert d.create_schema is None


def test_crud_router_body_create_schema_strips_path_filters():
    crud_router(
        District,
        list_item_schema=DistrictListSchema,
        read_schema=DistrictReadSchema,
        create_schema=DistrictCreateSchema,
        get_db=fake_get_db,
        crud_endpoints=["list", "read", "create"],
        path_filters={"city_id": "city_id"},
        create=CreateConfig(),
        list=ListConfig(),
    )
    d = iter_cruds()[0]
    assert d.path_filters == {"city_id": "city_id"}
    assert "city_id" in d.create_schema.model_fields
    assert "city_id" not in d.body_create_schema.model_fields


def test_m2m_router_registers_declaration():
    class UserSchema(BaseModel):
        id: int
        name: str

    m2m_router(
        parent_model=District,
        child_model=User,
        association_table=district_allowed_users,
        child_schema=UserSchema,
        prefix="/districts",
        get_db=fake_get_db,
    )
    decls = iter_m2ms()
    assert len(decls) == 1
    d = decls[0]
    assert d.relation == "users"
    assert d.parent_model is District
    assert d.child_model is User
    assert d.spec.child_schema is UserSchema
    # No login_dep wired → login not enforced (router parity)
    assert d.spec.login_enforced is False


def test_registry_reset():
    _make_router()
    assert iter_cruds()
    reset()
    assert iter_cruds() == ()
    assert iter_m2ms() == ()
