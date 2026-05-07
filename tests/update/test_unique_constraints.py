from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import UpdateConfig, update_endpoint
from tests.conftest import Tag, TagSchema, TagUpdateSchema


def _make_tag_app(engine) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    update_endpoint(
        router=app.router,
        path="/tags/{id}",
        model=Tag,
        update_schema=TagUpdateSchema,
        read_schema=TagSchema,
        config=UpdateConfig(login_required=False),
        get_db=get_db,
    )
    return app


@pytest_asyncio.fixture
async def tag_setup(db_session: AsyncSession, seed):
    t1 = Tag(id=201, name="news", slug="news", code="NEWS", city_id=1)
    t2 = Tag(id=202, name="news", slug="news-london", code="LONDON-NEWS", city_id=2)
    t3 = Tag(id=203, name="weather", slug="weather", code="WEATHER", city_id=1)
    db_session.add_all([t1, t2, t3])
    await db_session.commit()
    yield [t1, t2, t3]
    for tag_id in (201, 202, 203):
        obj = await db_session.get(Tag, tag_id)
        if obj is not None:
            await db_session.delete(obj)
    await db_session.commit()


# ---------------------------------------------------------------------------
# pk-exclude: PATCHing a row's own values must not conflict with itself
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_unchanged_slug_succeeds(engine, tag_setup):
    app = _make_tag_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch("/tags/201", json={"slug": "news"})
    assert r.status_code == 200, r.json()
    assert r.json()["slug"] == "news"


# ---------------------------------------------------------------------------
# Conflicting PATCH on a single-column unique field
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_to_conflicting_slug_returns_422(engine, tag_setup):
    app = _make_tag_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Move tag 203 onto tag 201's slug
        r = await client.patch("/tags/203", json={"slug": "news"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["message"] == "Validation failed"
    assert detail["fields"] == {"slug": ["Already exists"]}


# ---------------------------------------------------------------------------
# PATCH that triggers a composite collision
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_composite_conflict_returns_422(engine, tag_setup):
    """Tag 203 ('weather', city_id=1) renamed to 'news' would clash with tag
    201 on (city_id, name)."""
    app = _make_tag_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch("/tags/203", json={"name": "news"})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["message"] == "Validation failed"
    assert detail["fields"] == {
        "city_id": ["Already exists"],
        "name": ["Already exists"],
    }


# ---------------------------------------------------------------------------
# PATCH that does not touch any unique field
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_non_unique_field_succeeds(engine, tag_setup, db_session: AsyncSession):
    """The pre-flight check should pass when the PATCH leaves all unique-constrained
    columns at their existing (non-colliding) values."""
    # Tag 203 is ('weather', city_id=1, slug='weather', code='WEATHER').
    # Patch only the slug to a fresh, non-colliding value.
    app = _make_tag_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch("/tags/203", json={"slug": "weather-fresh"})
    assert r.status_code == 200, r.json()
    assert r.json()["slug"] == "weather-fresh"
