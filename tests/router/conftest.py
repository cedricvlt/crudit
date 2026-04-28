from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import crud_router
from tests.conftest import District


def _make_app(engine, current_user: Any = None, **crud_router_kwargs) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def get_current_user() -> Any:
        return current_user

    router = crud_router(get_db=get_db, **crud_router_kwargs)
    app.include_router(router, prefix="/districts")
    return app


@asynccontextmanager
async def _client(engine, current_user: Any = None, **kwargs):
    app = _make_app(engine, current_user, **kwargs)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
def make_client(engine):
    """Returns an async context manager: `async with make_client(...) as client`."""
    return lambda **kw: _client(engine, **kw)


@pytest_asyncio.fixture
async def cleanup_districts(engine):
    """Yields a list; deletes every District id appended to it after the test."""
    ids: list[int] = []
    yield ids
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        for district_id in ids:
            obj = await session.get(District, district_id)
            if obj:
                await session.delete(obj)
        await session.commit()


@pytest_asyncio.fixture
async def router_delete_target(engine, seed):
    """District (id=100) created in its own session; safe teardown after delete test."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        d = District(id=100, name="ToDelete", city_id=1, company_id=1, is_active=True)
        session.add(d)
        await session.commit()

    yield 100

    async with factory() as session:
        obj = await session.get(District, 100)
        if obj:
            await session.delete(obj)
            await session.commit()
