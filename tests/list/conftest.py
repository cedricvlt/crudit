from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudite import ListConfig, list_endpoint
from tests.conftest import District, DistrictSchema


def make_app(engine, config: ListConfig, current_user: Any = None) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def get_current_user() -> Any:
        return current_user

    config.login_dep = get_current_user

    list_endpoint(
        router=app.router,
        path="/cities/{city_id}/districts",
        model=District,
        schema=DistrictSchema,
        config=config,
        get_db=get_db,
    )
    return app


@pytest_asyncio.fixture
def make_client(engine):
    async def _make_client(config: ListConfig, current_user: Any = None) -> AsyncClient:
        app = make_app(engine, config, current_user)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return _make_client
