from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import M2MConfig, m2m_router
from tests.conftest import District, User, district_allowed_users


class UserSchema(BaseModel):
    id: int
    name: str


def make_app(
    engine,
    login_dep=None,
    login_required: bool = False,
    permission_dep=None,
    child_path_segment: str | None = None,
) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    router = m2m_router(
        parent_model=District,
        child_model=User,
        association_table=district_allowed_users,
        child_schema=UserSchema,
        prefix="/districts",
        get_db=get_db,
        config=M2MConfig(
            login_required=login_required,
            child_path_segment=child_path_segment,
        ),
        login_dep=login_dep,
        permission_dep=permission_dep,
    )
    app.include_router(router)
    return app


@pytest_asyncio.fixture
def make_client(engine):
    async def _make_client(
        login_dep=None,
        login_required: bool = False,
        permission_dep=None,
        child_path_segment: str | None = None,
    ) -> AsyncClient:
        app = make_app(
            engine,
            login_dep=login_dep,
            login_required=login_required,
            permission_dep=permission_dep,
            child_path_segment=child_path_segment,
        )
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    return _make_client
