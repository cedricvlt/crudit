from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import ReorderConfig, reorder_endpoint
from tests.conftest import District


def make_reorder_app(
    engine,
    config: ReorderConfig,
    path: str = "/districts/reorder",
    current_user: Any = None,
    permission_dep: Any = None,
) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def get_current_user() -> Any:
        return current_user

    reorder_endpoint(
        router=app.router,
        path=path,
        model=District,
        config=config,
        login_dep=get_current_user,
        permission_dep=permission_dep,
        get_db=get_db,
    )
    return app


@pytest_asyncio.fixture
def make_reorder_client(engine):
    async def _make(
        config: ReorderConfig,
        path: str = "/districts/reorder",
        current_user: Any = None,
        permission_dep: Any = None,
    ) -> AsyncClient:
        app = make_reorder_app(engine, config, path, current_user, permission_dep)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return _make


async def get_sort_order(engine, district_id: int) -> int | None:
    """Read sort_order directly from DB, bypassing any session cache."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(select(District).where(District.id == district_id))
        obj = result.scalar_one_or_none()
        return obj.sort_order if obj else None
