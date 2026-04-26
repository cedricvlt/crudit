from __future__ import annotations

import pytest
from pydantic import BaseModel

from crudite.exceptions import CruditeConfigError
from crudite.joins import resolve_joins
from tests.conftest import District


class CitySchema(BaseModel):
    id: int
    name: str


class DistrictWithCity(BaseModel):
    id: int
    name: str
    city: CitySchema


class DistrictWithCityList(BaseModel):
    id: int
    name: str
    cities: list[CitySchema]


class DistrictNoJoin(BaseModel):
    id: int
    name: str


def test_detects_m2o_join():
    info = resolve_joins(District, DistrictWithCity)
    assert "city" in info.joined_models
    assert "city" in info.m2o_rels
    assert len(info.eager_load_options(District, set())) == 1


def test_no_nested_schema_no_joins():
    info = resolve_joins(District, DistrictNoJoin)
    assert info.joined_models == {}
    assert info.eager_load_options(District, set()) == []


def test_unknown_relationship_raises():
    class BadSchema(BaseModel):
        id: int
        nonexistent: CitySchema

    with pytest.raises(CruditeConfigError, match="nonexistent"):
        resolve_joins(District, BadSchema)


@pytest.mark.asyncio
async def test_joined_data_in_response(seed, make_client):
    from crudite import ListConfig

    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) > 0
        for row in data:
            assert "city" in row
            assert row["city"]["name"] == "Paris"
