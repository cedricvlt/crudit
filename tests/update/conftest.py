from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import UpdateConfig, update_endpoint
from tests.conftest import District, DistrictSchema, DistrictUpdateSchema


def make_update_app(engine, config: UpdateConfig, current_user: Any = None, permission_dep: Any = None) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def get_current_user() -> Any:
        return current_user

    update_endpoint(
        router=app.router,
        path="/districts/{id}",
        model=District,
        update_schema=DistrictUpdateSchema,
        read_schema=DistrictSchema,
        config=config,
        login_dep=get_current_user,
        permission_dep=permission_dep,
        get_db=get_db,
    )
    return app


@pytest_asyncio.fixture
def make_update_client(engine):
    async def _make(config: UpdateConfig, current_user: Any = None, permission_dep: Any = None) -> AsyncClient:
        app = make_update_app(engine, config, current_user, permission_dep)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return _make


@pytest_asyncio.fixture
async def cleanup_districts(db_session: AsyncSession):
    ids: list[int] = []
    yield ids
    for district_id in ids:
        obj = await db_session.get(District, district_id)
        if obj:
            await db_session.delete(obj)
    await db_session.commit()
