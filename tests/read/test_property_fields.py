from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker

from crudit import ReadConfig, read_endpoint
from tests.conftest import District


class DistrictSummarySchema(BaseModel):
    label: str
    active: bool


class DistrictWithPropsSchema(BaseModel):
    id: int
    name: str
    display_name: str
    summary: DistrictSummarySchema


def _make_client(engine, config: ReadConfig) -> AsyncClient:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator:
        async with session_factory() as session:
            yield session

    async def get_current_user() -> Any:
        return None

    read_endpoint(
        router=app.router,
        path="/districts/{id}",
        model=District,
        schema=DistrictWithPropsSchema,
        config=config,
        login_dep=get_current_user,
        get_db=get_db,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_read_returns_scalar_property(seed, engine):
    async with _make_client(engine, ReadConfig(login_required=False)) as client:
        r = await client.get("/districts/1")
        assert r.status_code == 200
        body = r.json()
        assert body["display_name"] == f"{body['name']} #{body['id']}"


@pytest.mark.asyncio
async def test_read_returns_basemodel_property(seed, engine):
    async with _make_client(engine, ReadConfig(login_required=False)) as client:
        r = await client.get("/districts/1")
        assert r.status_code == 200
        body = r.json()
        assert body["summary"]["label"] == body["name"]
        assert isinstance(body["summary"]["active"], bool)
