from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import CreateConfig, create_endpoint
from tests.conftest import Tag, TagCreateSchema, TagSchema


def _make_tag_app(engine, *, before_create=None) -> FastAPI:
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    config = CreateConfig(
        login_required=False,
        before_create=before_create,
    )
    create_endpoint(
        router=app.router,
        path="/tags",
        model=Tag,
        create_schema=TagCreateSchema,
        read_schema=TagSchema,
        config=config,
        get_db=get_db,
    )
    return app


@pytest_asyncio.fixture
async def tag_setup(db_session: AsyncSession, seed):
    """Insert two seed tags; track created ids for cleanup."""
    t1 = Tag(id=101, name="news", slug="news", code="NEWS", city_id=1)
    t2 = Tag(id=102, name="news", slug="news-london", code="LONDON-NEWS", city_id=2)
    db_session.add_all([t1, t2])
    await db_session.commit()

    extra_ids: list[int] = []
    yield {"tags": [t1, t2], "extra_ids": extra_ids}

    for tag_id in [101, 102, *extra_ids]:
        obj = await db_session.get(Tag, tag_id)
        if obj is not None:
            await db_session.delete(obj)
    await db_session.commit()


# ---------------------------------------------------------------------------
# Pre-flight: column-level unique=True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_duplicate_slug_returns_422(engine, tag_setup):
    app = _make_tag_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/tags",
            json={"name": "sport", "slug": "news", "code": "SPORT", "city_id": 1},
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["message"] == "Validation failed"
    assert detail["fields"] == {"slug": ["Already exists"]}


# ---------------------------------------------------------------------------
# Pre-flight: composite UniqueConstraint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_duplicate_composite_returns_422(engine, tag_setup):
    app = _make_tag_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/tags",
            json={"name": "news", "slug": "news-paris", "code": "PARIS-NEWS", "city_id": 1},
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["message"] == "Validation failed"
    assert detail["fields"] == {
        "city_id": ["Already exists"],
        "name": ["Already exists"],
    }


@pytest.mark.asyncio
async def test_create_unique_name_per_city_succeeds(engine, tag_setup):
    """Composite (city_id, name) lets the same name exist under a different city."""
    app = _make_tag_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # city 2 already has ('news') from tag_setup. Use a fresh (city, name) pair.
        r = await client.post(
            "/tags",
            json={"name": "weather", "slug": "weather-paris", "code": "WEATHER", "city_id": 1},
        )
    assert r.status_code == 201, r.json()
    tag_setup["extra_ids"].append(r.json()["id"])


# ---------------------------------------------------------------------------
# Pre-flight: unique Index
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_duplicate_code_returns_422(engine, tag_setup):
    app = _make_tag_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/tags",
            json={"name": "weather", "slug": "weather", "code": "NEWS", "city_id": 1},
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["message"] == "Validation failed"
    assert detail["fields"] == {"code": ["Already exists"]}


# ---------------------------------------------------------------------------
# NULL bypass — SQL NULLs do not conflict
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_null_code_does_not_conflict(engine, tag_setup):
    app = _make_tag_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            "/tags",
            json={"name": "a", "slug": "tag-a", "code": None, "city_id": 1},
        )
        r2 = await client.post(
            "/tags",
            json={"name": "b", "slug": "tag-b", "code": None, "city_id": 1},
        )
    assert r1.status_code == 201, r1.json()
    assert r2.status_code == 201, r2.json()
    tag_setup["extra_ids"].extend([r1.json()["id"], r2.json()["id"]])


# ---------------------------------------------------------------------------
# IntegrityError fallback — pre-flight defeated by a hook that races
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_integrity_error_fallback(engine, tag_setup, monkeypatch):
    """If the pre-flight check is bypassed (e.g. a true race between two
    concurrent transactions), the IntegrityError from commit() must still
    surface as 422 — not 500.
    """
    from crudit.create import endpoint as create_endpoint_module

    async def noop_check(*args, **kwargs):
        return None

    monkeypatch.setattr(create_endpoint_module, "check_unique_constraints", noop_check)

    app = _make_tag_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/tags",
            json={"name": "race", "slug": "news", "code": "RACE", "city_id": 1},
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["message"] == "Validation failed"
