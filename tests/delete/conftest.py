from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import DeleteConfig, delete_endpoint
from tests.conftest import District, User


def make_delete_app(engine, config: DeleteConfig, current_user: Any = None) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def get_current_user() -> Any:
        return current_user

    config.login_dep = get_current_user

    delete_endpoint(
        router=app.router,
        path="/districts/{id}",
        model=District,
        config=config,
        get_db=get_db,
    )
    return app


@pytest_asyncio.fixture
def make_delete_client(engine):
    async def _make(config: DeleteConfig, current_user: Any = None) -> AsyncClient:
        app = make_delete_app(engine, config, current_user)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return _make


@pytest_asyncio.fixture
async def delete_target(engine, seed):
    """District (id=100, tenant_id=1) in its own session; safe teardown."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        d = District(id=100, name="ToDelete", city_id=1, tenant_id=1, is_active=True)
        session.add(d)
        await session.commit()

    yield

    async with factory() as session:
        obj = await session.get(District, 100)
        if obj:
            await session.delete(obj)
            await session.commit()


@pytest_asyncio.fixture
async def delete_target_allowed_user(engine, seed):
    """District (id=101, tenant_id=2) with user3 in allowed_users; own session."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user3 = await session.get(User, 3)
        d = District(id=101, name="ToDeleteAllowed", city_id=1, tenant_id=2, is_active=True)
        d.allowed_users.append(user3)
        session.add(d)
        await session.commit()

    yield

    async with factory() as session:
        obj = await session.get(District, 101)
        if obj:
            await session.delete(obj)
            await session.commit()


async def district_exists(engine, district_id: int) -> bool:
    """Check DB directly — bypasses any session identity-map cache."""
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(select(District).where(District.id == district_id))
        return result.scalar_one_or_none() is not None
