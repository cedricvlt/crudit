"""Tests for multi-level (>1) nested relationships in list/read endpoints."""
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import ListConfig, list_endpoint, read_endpoint
from crudit.read.config import ReadConfig
from crudit.joins import resolve_joins
from tests.conftest import City, Country, District


# ---------------------------------------------------------------------------
# Schemas with two-level nesting (District -> City -> Country)
# ---------------------------------------------------------------------------

class CountrySchema(BaseModel):
    id: int
    name: str


class CityWithCountrySchema(BaseModel):
    id: int
    name: str
    country: CountrySchema | None = None


class DistrictDeepSchema(BaseModel):
    id: int
    name: str
    city: CityWithCountrySchema


# ---------------------------------------------------------------------------
# resolve_joins builds a nested tree
# ---------------------------------------------------------------------------

def test_resolve_joins_walks_nested_schema():
    info = resolve_joins(District, DistrictDeepSchema)
    assert "city" in info.nodes
    city_node = info.nodes["city"]
    assert city_node.is_collection is False
    assert city_node.model is City
    assert "country" in city_node.children
    assert city_node.children["country"].model is Country
    assert city_node.children["country"].is_collection is False


def test_eager_load_options_chains_for_nested_path():
    info = resolve_joins(District, DistrictDeepSchema)
    options = info.eager_load_options(District, set())
    # one option for the city.country leaf — joinedload(District.city).joinedload(City.country)
    assert len(options) == 1


def test_eager_load_options_uses_contains_eager_for_explicitly_joined_chain():
    info = resolve_joins(District, DistrictDeepSchema)
    options = info.eager_load_options(District, {"city", "city.country"})
    # should produce a single chained contains_eager option
    assert len(options) == 1


# ---------------------------------------------------------------------------
# End-to-end list tests
# ---------------------------------------------------------------------------

_PATH_FILTERS = {"city_id": "city_id"}


def _make_app(
    engine,
    config: ListConfig,
    schema: type[BaseModel] = DistrictDeepSchema,
    path_filters: dict[str, str] | None = _PATH_FILTERS,
    path: str = "/cities/{city_id}/districts",
) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    list_endpoint(
        router=app.router,
        path=path,
        model=District,
        schema=schema,
        config=config,
        path_filters=path_filters,
        get_db=get_db,
    )
    return app


@pytest_asyncio.fixture
def deep_client(engine):
    def _make(config: ListConfig, **kwargs) -> AsyncClient:
        app = _make_app(engine, config, **kwargs)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return _make


@pytest.mark.asyncio
async def test_nested_eager_load_serialises_country(seed, deep_client):
    async with deep_client(ListConfig(login_required=False)) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        rows = r.json()["data"]
        assert len(rows) > 0
        for row in rows:
            assert row["city"]["country"]["name"] == "France"


@pytest.mark.asyncio
async def test_nested_filter_through_two_levels(seed, deep_client):
    config = ListConfig(login_required=False, filterable_fields=["city.country.name"])
    async with deep_client(config, path_filters=None, path="/districts") as client:
        r = await client.get("/districts?city.country.name=France")
        assert r.status_code == 200, r.text
        rows = r.json()["data"]
        names = {row["name"] for row in rows}
        assert names == {"Montmartre", "Marais"}


@pytest.mark.asyncio
async def test_nested_sort_through_two_levels(seed, deep_client):
    config = ListConfig(login_required=False, sortable_fields=["city.country.name"])
    async with deep_client(config, path_filters=None, path="/districts") as client:
        # ascending by country name: France districts first, then UK
        r = await client.get("/districts?sort=city.country.name")
        assert r.status_code == 200, r.text
        rows = r.json()["data"]
        country_names = [row["city"]["country"]["name"] for row in rows]
        assert country_names == sorted(country_names)


@pytest.mark.asyncio
async def test_nested_search_through_two_levels(seed, deep_client):
    config = ListConfig(login_required=False, search_fields=["city.country.name"])
    async with deep_client(config, path_filters=None, path="/districts") as client:
        r = await client.get("/districts?q=Fran")
        assert r.status_code == 200, r.text
        rows = r.json()["data"]
        names = {row["name"] for row in rows}
        assert names == {"Montmartre", "Marais"}


# ---------------------------------------------------------------------------
# Error: filtering through an o2m segment is rejected
# ---------------------------------------------------------------------------

class _CityFlat(BaseModel):
    id: int
    name: str


class CountryWithCitiesSchema(BaseModel):
    id: int
    name: str
    cities: list[_CityFlat] = []


def test_resolve_nested_column_rejects_o2m_segment():
    """A dotted path that includes an o2m segment cannot be JOINed without
    multiplying rows; resolve_nested_column raises a ValueError naming the
    offending segment."""
    from crudit.joins import resolve_nested_column

    info = resolve_joins(Country, CountryWithCitiesSchema)
    with pytest.raises(ValueError, match="cities"):
        resolve_nested_column("cities.name", Country, info)


# ---------------------------------------------------------------------------
# read_endpoint loads nested chain
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_endpoint_loads_nested_chain(engine, seed):
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db():
        async with session_factory() as session:
            yield session

    read_endpoint(
        router=app.router,
        path="/districts/{id}",
        model=District,
        schema=DistrictDeepSchema,
        config=ReadConfig(login_required=False),
        get_db=get_db,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/districts/1")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["city"]["country"]["name"] == "France"


# ---------------------------------------------------------------------------
# sort_o2m_collections recurses into nested o2m
# ---------------------------------------------------------------------------

def test_sort_o2m_collections_recurses_into_nested():
    from crudit.joins import JoinInfo, JoinNode

    class Leaf:
        _order_fields = ("name",)

        def __init__(self, name):
            self.name = name

    class Group:
        def __init__(self, leaves):
            self.leaves = leaves

    class Root:
        def __init__(self, groups):
            self.groups = groups

    leaves_node = JoinNode("leaves", Leaf, is_collection=True)
    groups_node = JoinNode("groups", Group, is_collection=True, children={"leaves": leaves_node})
    info = JoinInfo(nodes={"groups": groups_node})

    root = Root([
        Group([Leaf("c"), Leaf("a"), Leaf("b")]),
        Group([Leaf("z"), Leaf("y")]),
    ])
    info.sort_o2m_collections([root])

    assert [leaf.name for leaf in root.groups[0].leaves] == ["a", "b", "c"]
    assert [leaf.name for leaf in root.groups[1].leaves] == ["y", "z"]
