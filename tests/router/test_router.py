from __future__ import annotations

import pytest

from crudit import (
    ListConfig,
    OptionsConfig,
    SharedConfig,
    crud_router,
)
from crudit.exceptions import CruditConfigError
from tests.conftest import (
    City,
    CitySchema,
    District,
    DistrictCreateFlatSchema,
    DistrictSchema,
    DistrictUpdateSchema,
)

# Common kwargs shared by most route-registration tests
_FULL = dict(
    model=District,
    list_item_schema=DistrictSchema,
    read_schema=DistrictSchema,
    create_schema=DistrictCreateFlatSchema,
    update_schema=DistrictUpdateSchema,
    shared=SharedConfig(login_required=False),
)


# ---------------------------------------------------------------------------
# Validation errors at registration time
# ---------------------------------------------------------------------------

def test_unknown_crud_endpoint_raises():
    with pytest.raises(CruditConfigError, match="Unknown crud_endpoint"):
        crud_router(model=District, get_db=lambda: None, crud_endpoints=["list", "destroy"])


def test_unknown_extra_endpoint_raises():
    with pytest.raises(CruditConfigError, match="Unknown extra_endpoint"):
        crud_router(model=District, get_db=lambda: None, extra_endpoints=["options", "nope"])


def test_missing_list_item_schema_raises():
    with pytest.raises(CruditConfigError, match="list_item_schema"):
        crud_router(model=District, get_db=lambda: None, crud_endpoints=["list"])


def test_missing_read_schema_raises():
    with pytest.raises(CruditConfigError, match="read_schema"):
        crud_router(model=District, get_db=lambda: None, crud_endpoints=["read"])


def test_missing_create_schema_raises():
    with pytest.raises(CruditConfigError, match="create_schema"):
        crud_router(
            model=District,
            get_db=lambda: None,
            crud_endpoints=["create"],
            read_schema=DistrictSchema,
        )


def test_missing_update_schema_raises():
    with pytest.raises(CruditConfigError, match="update_schema"):
        crud_router(
            model=District,
            get_db=lambda: None,
            crud_endpoints=["update"],
            read_schema=DistrictSchema,
        )


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

async def test_list_endpoint_registered(seed, make_client):
    async with make_client(crud_endpoints=["list"], **_FULL) as client:
        r = await client.get("/districts")
        assert r.status_code == 200
        assert "data" in r.json()


async def test_read_endpoint_registered(seed, make_client):
    async with make_client(crud_endpoints=["read"], **_FULL) as client:
        r = await client.get("/districts/1")
        assert r.status_code == 200
        assert r.json()["id"] == 1


async def test_create_endpoint_registered(seed, make_client, cleanup_districts):
    async with make_client(crud_endpoints=["create"], **_FULL) as client:
        r = await client.post("/districts", json={"name": "New District", "city_id": 1})
    assert r.status_code == 201
    assert r.json()["name"] == "New District"
    cleanup_districts.append(r.json()["id"])


async def test_update_endpoint_registered(seed, make_client):
    async with make_client(crud_endpoints=["update"], **_FULL) as client:
        r = await client.patch("/districts/1", json={"name": "Renamed"})
        assert r.status_code == 200
        assert r.json()["name"] == "Renamed"


async def test_delete_endpoint_registered(router_delete_target, make_client):
    async with make_client(crud_endpoints=["delete"], **_FULL) as client:
        r = await client.delete(f"/districts/{router_delete_target}")
        assert r.status_code == 204


async def test_options_endpoint_registered(seed, make_client):
    # No explicit OptionsConfig — defaults to label_field="name"
    async with make_client(
        model=City,
        list_item_schema=CitySchema,
        crud_endpoints=[],
        extra_endpoints=["options"],
        shared=SharedConfig(login_required=False),
    ) as client:
        r = await client.get("/districts/options")
        assert r.status_code == 200
        assert all("id" in it and "label" in it for it in r.json()["data"])


async def test_option_schema_used_as_output(seed, make_client):
    from pydantic import BaseModel, Field

    class DistrictOptionSchema(BaseModel):
        id: int
        label: str = Field(validation_alias="name")
        city: CitySchema

    async with make_client(
        model=District,
        list_item_schema=DistrictSchema,
        option_schema=DistrictOptionSchema,
        crud_endpoints=[],
        extra_endpoints=["options"],
        shared=SharedConfig(login_required=False),
    ) as client:
        r = await client.get("/districts/options")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) > 0
        for it in data:
            assert set(it.keys()) == {"id", "label", "city"}
            assert "name" in it["city"]


async def test_reorder_endpoint_registered(seed, make_client):
    async with make_client(extra_endpoints=["reorder"], **_FULL) as client:
        r = await client.post("/districts/reorder", json={"ids": [2, 1]})
        assert r.status_code == 204


# ---------------------------------------------------------------------------
# Endpoint restriction
# ---------------------------------------------------------------------------

async def test_excluded_endpoints_not_registered(seed, make_client):
    async with make_client(crud_endpoints=["list"], **_FULL) as client:
        assert (await client.get("/districts")).status_code == 200
        # path /districts/{id} is never registered → 404
        assert (await client.get("/districts/1")).status_code == 404
        assert (await client.patch("/districts/1", json={})).status_code == 404
        assert (await client.delete("/districts/1")).status_code == 404
        # path /districts IS registered (GET), so excluded POST → 405
        assert (await client.post("/districts", json={})).status_code == 405


# ---------------------------------------------------------------------------
# Shared config propagation
# ---------------------------------------------------------------------------

async def test_shared_login_required_applied(seed, make_client):
    # With login_required=True and no user, list should 401/403
    async with make_client(
        model=District,
        list_item_schema=DistrictSchema,
        read_schema=DistrictSchema,
        crud_endpoints=["list"],
        shared=SharedConfig(login_required=True),
    ) as client:
        r = await client.get("/districts")
        assert r.status_code in (401, 403)


async def test_per_verb_config_overrides_shared(seed, make_client):
    # shared sets login_required=True, but list config overrides to False
    async with make_client(
        model=District,
        list_item_schema=DistrictSchema,
        read_schema=DistrictSchema,
        crud_endpoints=["list"],
        shared=SharedConfig(login_required=True),
        list=ListConfig(login_required=False),
    ) as client:
        assert (await client.get("/districts")).status_code == 200


# ---------------------------------------------------------------------------
# create/update reuse read_schema as output
# ---------------------------------------------------------------------------

async def test_create_returns_read_schema_fields(seed, make_client, cleanup_districts):
    async with make_client(crud_endpoints=["create"], **_FULL) as client:
        r = await client.post("/districts", json={"name": "Belleville", "city_id": 1})
    assert r.status_code == 201
    body = r.json()
    # DistrictSchema includes nested city — confirms read_schema is used for output
    assert "city" in body
    assert body["city"]["id"] == 1
    cleanup_districts.append(body["id"])


async def test_update_returns_read_schema_fields(seed, make_client):
    async with make_client(crud_endpoints=["update"], **_FULL) as client:
        r = await client.patch("/districts/1", json={"name": "Renamed"})
    assert r.status_code == 200
    # DistrictSchema includes nested city — confirms read_schema is used for output
    assert "city" in r.json()
