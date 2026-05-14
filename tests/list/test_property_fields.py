from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker

from crudit import ListConfig, list_endpoint
from crudit.exceptions import CruditConfigError
from tests.conftest import District


class DistrictSummarySchema(BaseModel):
    label: str
    active: bool


class DistrictWithPropsSchema(BaseModel):
    id: int
    name: str
    display_name: str
    summary: DistrictSummarySchema


def _make_client(engine, config: ListConfig) -> AsyncClient:
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
        schema=DistrictWithPropsSchema,
        config=config,
        path_filters={"city_id": "city_id"},
        login_dep=get_current_user,
        get_db=get_db,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_scalar_property_in_response(seed, engine):
    async with _make_client(engine, ListConfig(login_required=False)) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        rows = r.json()["data"]
        assert rows
        for row in rows:
            assert row["display_name"] == f"{row['name']} #{row['id']}"


@pytest.mark.asyncio
async def test_basemodel_property_in_response(seed, engine):
    async with _make_client(engine, ListConfig(login_required=False)) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        rows = r.json()["data"]
        assert rows
        for row in rows:
            assert row["summary"]["label"] == row["name"]
            assert isinstance(row["summary"]["active"], bool)


def test_property_in_filterable_fields_rejected(engine):
    with pytest.raises(CruditConfigError, match="display_name.*@property"):
        _make_client(
            engine,
            ListConfig(login_required=False, filterable_fields=["display_name"]),
        )


def test_property_in_sortable_fields_rejected(engine):
    with pytest.raises(CruditConfigError, match="display_name.*@property"):
        _make_client(
            engine,
            ListConfig(login_required=False, sortable_fields=["display_name"]),
        )


def test_property_in_search_fields_rejected(engine):
    with pytest.raises(CruditConfigError, match="display_name.*@property"):
        _make_client(
            engine,
            ListConfig(login_required=False, search_fields=["display_name"]),
        )
