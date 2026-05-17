from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import ReadConfig, read_endpoint
from crudit.exceptions import CruditConfigError
from tests.conftest import District, district_allowed_users


class DistrictWithCountSchema(BaseModel):
    id: int
    name: str
    allowed_user_count: int


def _make_app(engine, config: ReadConfig) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def get_current_user() -> Any:
        return None

    read_endpoint(
        router=app.router,
        path="/districts/{id}",
        model=District,
        schema=DistrictWithCountSchema,
        config=config,
        login_dep=get_current_user,
        get_db=get_db,
    )
    return app


def _allowed_user_count_subquery(model: type[District]):
    return (
        select(func.count(district_allowed_users.c.user_id))
        .where(district_allowed_users.c.district_id == model.id)
        .correlate(model)
        .scalar_subquery()
    )


@pytest.mark.asyncio
async def test_read_returns_computed_field(seed, engine):
    config = ReadConfig(
        login_required=False,
        computed_fields={"allowed_user_count": _allowed_user_count_subquery},
    )
    app = _make_app(engine, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/districts/1")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == 1
        assert body["allowed_user_count"] == 1


@pytest.mark.asyncio
async def test_read_computed_field_zero(seed, engine):
    config = ReadConfig(
        login_required=False,
        computed_fields={"allowed_user_count": _allowed_user_count_subquery},
    )
    app = _make_app(engine, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/districts/2")
        assert r.status_code == 200
        assert r.json()["allowed_user_count"] == 0


@pytest.mark.asyncio
async def test_read_not_found_with_computed_fields(seed, engine):
    config = ReadConfig(
        login_required=False,
        computed_fields={"allowed_user_count": _allowed_user_count_subquery},
    )
    app = _make_app(engine, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/districts/9999")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_read_computed_field_visible_in_after_query_hook(seed, engine):
    seen: list[Any] = []

    def after(obj, ctx):
        seen.append(obj)
        return obj

    config = ReadConfig(
        login_required=False,
        computed_fields={"allowed_user_count": _allowed_user_count_subquery},
        after_query=after,
    )
    app = _make_app(engine, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/districts/1")
        assert r.status_code == 200
    assert len(seen) == 1
    assert isinstance(seen[0], District)
    assert seen[0].allowed_user_count == 1


def test_read_computed_field_name_collision_raises(engine):
    config = ReadConfig(
        login_required=False,
        computed_fields={"name": _allowed_user_count_subquery},
    )
    with pytest.raises(CruditConfigError, match="collides"):
        _make_app(engine, config)


def test_read_computed_field_missing_from_schema_raises(engine):
    config = ReadConfig(
        login_required=False,
        computed_fields={"extra": _allowed_user_count_subquery},
    )
    with pytest.raises(CruditConfigError, match="not declared"):
        _make_app(engine, config)
