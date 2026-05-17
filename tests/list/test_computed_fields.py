from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import ListConfig, list_endpoint
from crudit.exceptions import CruditConfigError
from tests.conftest import District, district_allowed_users


class DistrictWithCountSchema(BaseModel):
    id: int
    name: str
    allowed_user_count: int


def _make_app(engine, config: ListConfig) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def get_current_user() -> Any:
        return None

    list_endpoint(
        router=app.router,
        path="/cities/{city_id}/districts",
        model=District,
        schema=DistrictWithCountSchema,
        config=config,
        path_filters={"city_id": "city_id"},
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
async def test_computed_field_returns_aggregate(seed, engine):
    config = ListConfig(
        login_required=False,
        computed_fields={"allowed_user_count": _allowed_user_count_subquery},
    )
    app = _make_app(engine, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        by_id = {d["id"]: d for d in r.json()["data"]}
        # d1 has user3 in allowed_users, d2 has none
        assert by_id[1]["allowed_user_count"] == 1
        assert by_id[2]["allowed_user_count"] == 0


@pytest.mark.asyncio
async def test_computed_field_with_pagination(seed, engine):
    config = ListConfig(
        login_required=False,
        computed_fields={"allowed_user_count": _allowed_user_count_subquery},
    )
    app = _make_app(engine, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/cities/2/districts?page=1&itemsPerPage=1")
        assert r.status_code == 200
        body = r.json()
        assert body["totalCount"] == 2
        assert len(body["data"]) == 1
        assert "allowed_user_count" in body["data"][0]


@pytest.mark.asyncio
async def test_computed_field_visible_in_after_query_hook(seed, engine):
    seen: list[Any] = []

    def after(rows, ctx):
        seen.extend(rows)
        return rows

    config = ListConfig(
        login_required=False,
        computed_fields={"allowed_user_count": _allowed_user_count_subquery},
        after_query=after,
    )
    app = _make_app(engine, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
    # Rows passed to the hook are ORM instances with the computed attribute set.
    assert all(isinstance(row, District) for row in seen)
    by_id = {row.id: row for row in seen}
    assert by_id[1].allowed_user_count == 1
    assert by_id[2].allowed_user_count == 0


@pytest.mark.asyncio
async def test_sort_by_computed_field_asc(seed, engine):
    config = ListConfig(
        login_required=False,
        computed_fields={"allowed_user_count": _allowed_user_count_subquery},
    )
    app = _make_app(engine, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/cities/1/districts?sort=allowed_user_count")
        assert r.status_code == 200
        ids = [d["id"] for d in r.json()["data"]]
        # d2 has 0, d1 has 1 → ascending puts d2 first
        assert ids == [2, 1]


@pytest.mark.asyncio
async def test_sort_by_computed_field_desc(seed, engine):
    config = ListConfig(
        login_required=False,
        computed_fields={"allowed_user_count": _allowed_user_count_subquery},
    )
    app = _make_app(engine, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/cities/1/districts?sort=-allowed_user_count")
        assert r.status_code == 200
        ids = [d["id"] for d in r.json()["data"]]
        assert ids == [1, 2]


@pytest.mark.asyncio
async def test_count_only_works_with_computed_fields(seed, engine):
    config = ListConfig(
        login_required=False,
        computed_fields={"allowed_user_count": _allowed_user_count_subquery},
    )
    app = _make_app(engine, config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/cities/1/districts?countOnly=true")
        assert r.status_code == 200
        assert r.json() == {"totalCount": 2}


def test_computed_field_name_collides_with_column_raises(engine):
    """'name' is a real column on District — must be rejected."""
    config = ListConfig(
        login_required=False,
        computed_fields={"name": _allowed_user_count_subquery},
    )
    with pytest.raises(CruditConfigError, match="collides"):
        _make_app(engine, config)


def test_computed_field_missing_from_schema_raises(engine):
    """Computed field 'extra' is not declared on the response schema."""
    config = ListConfig(
        login_required=False,
        computed_fields={"extra": _allowed_user_count_subquery},
    )
    with pytest.raises(CruditConfigError, match="not declared"):
        _make_app(engine, config)


