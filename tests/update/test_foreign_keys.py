from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import UpdateConfig, update_endpoint
from tests.conftest import (
    Company,
    District,
    DistrictSchema,
    Tag,
    TagSchema,
    TagUpdateSchema,
    User,
)


class DistrictUpdateFKSchema(BaseModel):
    """Test schema exposing FKs in the PATCH body."""
    name: str | None = None
    is_active: bool | None = None
    city_id: int | None = None
    company_id: int | None = None


def _make_district_app(
    engine,
    *,
    current_user: Any = None,
    update_schema: type[BaseModel] = DistrictUpdateFKSchema,
) -> FastAPI:
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
        update_schema=update_schema,
        read_schema=DistrictSchema,
        config=UpdateConfig(login_required=False),
        login_dep=get_current_user,
        get_db=get_db,
    )
    return app


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
    t1 = Tag(id=301, name="news", slug="news", code="NEWS", city_id=1)
    t2 = Tag(id=302, name="weather", slug="weather", code="WEATHER", city_id=1)
    db_session.add_all([t1, t2])
    await db_session.commit()
    yield [t1, t2]
    for tag_id in (301, 302):
        obj = await db_session.get(Tag, tag_id)
        if obj is not None:
            await db_session.delete(obj)
    await db_session.commit()


# ---------------------------------------------------------------------------
# PATCH without any FK column: no FK pre-flight is needed and no error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_no_fk_in_patch_succeeds(engine, seed):
    app = _make_district_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch("/districts/1", json={"name": "Renamed"})
    assert r.status_code == 200, r.json()
    assert r.json()["name"] == "Renamed"


# ---------------------------------------------------------------------------
# PATCH with an invalid FK
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_invalid_fk_returns_422(engine, seed):
    app = _make_district_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch("/districts/1", json={"city_id": 9999})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["message"] == "Validation failed"
    assert detail["fields"] == {"city_id": ["Does not exist"]}


# ---------------------------------------------------------------------------
# PATCH that moves a row to a valid FK
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_valid_fk_change_succeeds(engine, seed):
    app = _make_district_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch("/districts/1", json={"city_id": 2})
    assert r.status_code == 200, r.json()
    assert r.json()["city_id"] == 2


# ---------------------------------------------------------------------------
# PATCH with multiple invalid FKs reports both
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_multiple_invalid_fks_returns_422_with_all(engine, seed):
    app = _make_district_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch(
            "/districts/1",
            json={"city_id": 9999, "company_id": 8888},
        )
    assert r.status_code == 422
    assert r.json()["detail"]["fields"] == {
        "city_id": ["Does not exist"],
        "company_id": ["Does not exist"],
    }


# ---------------------------------------------------------------------------
# PATCH setting a nullable FK to None: skipped, succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_null_nullable_fk_succeeds(engine, seed):
    app = _make_district_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch("/districts/1", json={"company_id": None})
    assert r.status_code == 200, r.json()


# ---------------------------------------------------------------------------
# updated_by_id auto-set from current_user, skipped by the pre-flight
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_updated_by_id_skipped(engine, seed):
    # company_id=1 matches District(id=1) for the row-level permission check;
    # id=9999 doesn't reference any real User row, which is what we're testing.
    fake_user = User(id=9999, name="Ghost", companies=[Company(id=1)])
    app = _make_district_app(engine, current_user=fake_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch("/districts/1", json={"name": "Touch"})
    assert r.status_code == 200, r.json()
    assert r.json()["updated_by_id"] == 9999


# ---------------------------------------------------------------------------
# Ordering: FK check runs before unique check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_fk_check_runs_before_unique_check(engine, tag_setup):
    """PATCH that would trigger BOTH an invalid FK and a unique-slug collision
    must surface the FK error (FK check is ordered first).
    """
    app = _make_tag_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Tag 302 ('weather') tries to take slug 'news' (collision with 301)
        # AND move to city 9999 (invalid FK).
        r = await client.patch(
            "/tags/302",
            json={"slug": "news", "city_id": 9999},
        )
    assert r.status_code == 422
    fields = r.json()["detail"]["fields"]
    assert "city_id" in fields
    assert fields["city_id"] == ["Does not exist"]
    # The unique-slug collision must NOT have been reported (FK ran first).
    assert "slug" not in fields


# ---------------------------------------------------------------------------
# IntegrityError fallback: pre-flight defeated, commit fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_integrity_error_fallback(engine, seed):
    """If pre-flight is bypassed and commit raises IntegrityError, the chained
    translator still produces 422.
    """
    from sqlalchemy.exc import IntegrityError

    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db_raising():
        async with session_factory() as session:
            orig_commit = session.commit

            async def fake_commit():
                raise IntegrityError("UPDATE", {}, Exception("fk violation"))

            session.commit = fake_commit  # type: ignore[method-assign]
            try:
                yield session
            finally:
                session.commit = orig_commit  # type: ignore[method-assign]

    update_endpoint(
        router=app.router,
        path="/districts/{id}",
        model=District,
        update_schema=DistrictUpdateFKSchema,
        read_schema=DistrictSchema,
        config=UpdateConfig(login_required=False),
        get_db=get_db_raising,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.patch("/districts/1", json={"city_id": 2})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["message"] == "Validation failed"
