from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import CreateConfig, create_endpoint
from tests.conftest import District, DistrictCreateSchema, DistrictSchema


def make_create_app(
    engine,
    config: CreateConfig,
    current_user: Any = None,
    path: str = "/cities/{city_id}/districts",
) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def get_current_user() -> Any:
        return current_user

    config.login_dep = get_current_user

    create_endpoint(
        router=app.router,
        path=path,
        model=District,
        create_schema=DistrictCreateSchema,
        read_schema=DistrictSchema,
        config=config,
        get_db=get_db,
    )
    return app


@pytest_asyncio.fixture
def make_create_client(engine):
    async def _make(
        config: CreateConfig,
        current_user: Any = None,
        path: str = "/cities/{city_id}/districts",
    ) -> AsyncClient:
        app = make_create_app(engine, config, current_user, path)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return _make


@pytest_asyncio.fixture
async def cleanup_districts(db_session: AsyncSession):
    """Yields a list; after the test deletes every District id added to it."""
    ids: list[int] = []
    yield ids
    for district_id in ids:
        obj = await db_session.get(District, district_id)
        if obj:
            await db_session.delete(obj)
    await db_session.commit()
