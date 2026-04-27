from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import OptionsConfig, options_endpoint
from tests.conftest import District, DistrictSchema


def make_app(
    engine,
    config: OptionsConfig,
    current_user: Any = None,
    schema: type[BaseModel] | None = None,
    permission_dep: Any = None,
) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def get_current_user() -> Any:
        return current_user

    options_endpoint(
        router=app.router,
        path="/cities/{city_id}/districts",
        model=District,
        config=config,
        login_dep=get_current_user,
        permission_dep=permission_dep,
        schema=schema or DistrictSchema,
        get_db=get_db,
    )
    return app


@pytest_asyncio.fixture
def make_client(engine):
    async def _make_client(
        config: OptionsConfig,
        current_user: Any = None,
        schema: type[BaseModel] | None = None,
        permission_dep: Any = None,
    ) -> AsyncClient:
        app = make_app(engine, config, current_user, schema, permission_dep)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return _make_client
