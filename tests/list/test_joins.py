from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import ListConfig, list_endpoint
from crudit.exceptions import CruditConfigError
from crudit.joins import resolve_joins
from tests.conftest import City, District


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

    with pytest.raises(CruditConfigError, match="nonexistent"):
        resolve_joins(District, BadSchema)


class DistrictSimpleSchema(BaseModel):
    id: int
    name: str


class CityWithDistrictsSchema(BaseModel):
    id: int
    name: str
    districts: list[DistrictSimpleSchema]


@pytest_asyncio.fixture
def make_city_client(engine):
    def _make(config: ListConfig, current_user: Any = None):
        app = FastAPI()
        session_factory = async_sessionmaker(engine, expire_on_commit=False)

        async def get_db() -> AsyncGenerator[AsyncSession, None]:
            async with session_factory() as session:
                yield session

        async def get_current_user() -> Any:
            return current_user

        list_endpoint(
            router=app.router,
            path="/cities",
            model=City,
            schema=CityWithDistrictsSchema,
            config=config,
            login_dep=get_current_user,
            get_db=get_db,
        )
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return _make


@pytest.mark.asyncio
async def test_o2m_joined_items_sorted_by_order_fields(seed, make_city_client):
    async with make_city_client(ListConfig(login_required=False)) as client:
        r = await client.get("/cities")
        assert r.status_code == 200
        cities = r.json()["data"]
        paris = next(c for c in cities if c["name"] == "Paris")
        district_names = [d["name"] for d in paris["districts"]]
        assert district_names == sorted(district_names)


@pytest.mark.asyncio
async def test_joined_data_in_response(seed, make_client):
    from crudit import ListConfig

    async with await make_client(
        ListConfig(
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
