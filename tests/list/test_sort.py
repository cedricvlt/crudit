from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker

from crudit import ListConfig, list_endpoint


SORTABLE = ["name", "is_active", "city.name"]


@pytest.mark.asyncio
async def test_default_sort(seed, make_client):
    async with await make_client(
        ListConfig(
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        names = [d["name"] for d in r.json()["data"]]
        assert names == sorted(names)


@pytest.mark.asyncio
async def test_sort_asc(seed, make_client):
    async with await make_client(
        ListConfig(
            sortable_fields=SORTABLE,
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=name")
        assert r.status_code == 200
        names = [d["name"] for d in r.json()["data"]]
        assert names == sorted(names)


@pytest.mark.asyncio
async def test_sort_desc(seed, make_client):
    async with await make_client(
        ListConfig(
            sortable_fields=SORTABLE,
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=-name")
        assert r.status_code == 200
        names = [d["name"] for d in r.json()["data"]]
        assert names == sorted(names, reverse=True)


@pytest.mark.asyncio
async def test_sort_nested(seed, make_client):
    async with await make_client(
        ListConfig(
            sortable_fields=["city.name", "name"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=city.name,-name")
        assert r.status_code == 200
        assert r.json()["totalCount"] > 0


@pytest.mark.asyncio
async def test_unknown_sort_returns_400(seed, make_client):
    async with await make_client(
        ListConfig(
            sortable_fields=["name"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=secret")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Auto-defaulting sortable_fields from the schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_field_auto_sortable_without_explicit_listing(seed, make_client):
    # `name` is in DistrictSchema but not in config.sortable_fields — it
    # should still be sortable because the schema declares it.
    async with await make_client(
        ListConfig(login_required=False),
    ) as client:
        r = await client.get("/cities/1/districts?sort=-name")
        assert r.status_code == 200
        names = [d["name"] for d in r.json()["data"]]
        assert names == sorted(names, reverse=True)


@pytest.mark.asyncio
async def test_nested_schema_field_auto_sortable(seed, make_client):
    # DistrictSchema has `city: CitySchema` — city.name should be sortable
    # even without listing it.
    async with await make_client(
        ListConfig(login_required=False),
        path_filters=None,
    ) as client:
        r = await client.get("/cities/1/districts?sort=city.name")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_explicit_sortable_field_still_works(seed, make_client):
    # Explicit sortable_fields are appended to the auto-defaulted list, not
    # replacing it: both schema-derived `name` and the custom alias work.
    async with await make_client(
        ListConfig(
            sortable_fields=["created_by_id"],  # not in default _order_fields
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=name")
        assert r.status_code == 200
        r2 = await client.get("/cities/1/districts?sort=created_by_id")
        assert r2.status_code == 200


# ---------------------------------------------------------------------------
# Auto-defaulting must skip property fields and o2m relationships
# ---------------------------------------------------------------------------


class _UserOpt(BaseModel):
    id: int
    name: str


class _DistrictWithO2MSchema(BaseModel):
    id: int
    name: str
    allowed_users: list[_UserOpt]


class _DistrictSummarySchema(BaseModel):
    label: str
    active: bool


class _DistrictWithPropsSchema(BaseModel):
    id: int
    name: str
    display_name: str
    summary: _DistrictSummarySchema


def _make_app(engine, schema, config: ListConfig) -> FastAPI:
    from tests.conftest import District

    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator:
        async with session_factory() as session:
            yield session

    async def get_current_user() -> Any:
        return None

    list_endpoint(
        router=app.router,
        path="/cities/{city_id}/districts",
        model=District,
        schema=schema,
        config=config,
        path_filters={"city_id": "city_id"},
        login_dep=get_current_user,
        get_db=get_db,
    )
    return app


@pytest.mark.asyncio
async def test_o2m_nested_field_not_auto_sortable(seed, engine):
    app = _make_app(engine, _DistrictWithO2MSchema, ListConfig(login_required=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/cities/1/districts?sort=allowed_users.name")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_property_field_not_auto_sortable(seed, engine):
    app = _make_app(engine, _DistrictWithPropsSchema, ListConfig(login_required=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/cities/1/districts?sort=display_name")
        assert r.status_code == 400
        # `summary` is a nested BaseModel returned by a @property — its
        # nested fields must not be auto-included either.
        r2 = await client.get("/cities/1/districts?sort=summary.label")
        assert r2.status_code == 400
