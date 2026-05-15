from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crudit import CreateConfig, ParentParam, create_endpoint
from tests.conftest import City, District, DistrictCreateSchema, DistrictSchema, User


class DistrictCreateFKSchema(BaseModel):
    """Test schema exposing both required and nullable FKs in the body."""
    name: str
    is_active: bool = True
    city_id: int
    company_id: int | None = None


def _make_flat_app(
    engine,
    *,
    current_user: Any = None,
    create_schema: type[BaseModel] = DistrictCreateFKSchema,
) -> FastAPI:
    """Build a FastAPI app with /districts (no parent_params, no path_filters).

    Used by tests that exercise body-FK validation directly.
    """
    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def get_current_user() -> Any:
        return current_user

    create_endpoint(
        router=app.router,
        path="/districts",
        model=District,
        create_schema=create_schema,
        read_schema=DistrictSchema,
        config=CreateConfig(login_required=False),
        login_dep=get_current_user,
        get_db=get_db,
    )
    return app


@pytest_asyncio.fixture
async def cleanup_districts(db_session: AsyncSession):
    ids: list[int] = []
    yield ids
    for district_id in ids:
        obj = await db_session.get(District, district_id)
        if obj:
            await db_session.delete(obj)
    await db_session.commit()


# ---------------------------------------------------------------------------
# Body-FK pre-flight: required FK missing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_invalid_required_fk_returns_422(engine, seed):
    app = _make_flat_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/districts",
            json={"name": "Ghost", "city_id": 9999},
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["message"] == "Validation failed"
    assert detail["fields"] == {"city_id": ["Does not exist"]}


# ---------------------------------------------------------------------------
# Body-FK pre-flight: nullable FK missing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_invalid_nullable_fk_returns_422(engine, seed):
    app = _make_flat_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/districts",
            json={"name": "Ghost", "city_id": 1, "company_id": 9999},
        )
    assert r.status_code == 422
    assert r.json()["detail"]["fields"] == {"company_id": ["Does not exist"]}


# ---------------------------------------------------------------------------
# Body-FK pre-flight: nullable FK set to None is skipped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_null_nullable_fk_succeeds(engine, seed, cleanup_districts):
    app = _make_flat_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/districts",
            json={"name": "NullCo", "city_id": 1, "company_id": None},
        )
    assert r.status_code == 201, r.json()
    cleanup_districts.append(r.json()["id"])


# ---------------------------------------------------------------------------
# Body-FK pre-flight: multiple invalid FKs reported in one response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_multiple_invalid_fks_returns_422_with_all(engine, seed):
    app = _make_flat_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/districts",
            json={"name": "Ghost", "city_id": 9999, "company_id": 8888},
        )
    assert r.status_code == 422
    assert r.json()["detail"]["fields"] == {
        "city_id": ["Does not exist"],
        "company_id": ["Does not exist"],
    }


# ---------------------------------------------------------------------------
# Body-FK pre-flight: valid FKs succeed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_valid_fks_returns_201(engine, seed, cleanup_districts):
    app = _make_flat_app(engine)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/districts",
            json={"name": "Real", "city_id": 1, "company_id": 1},
        )
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["city_id"] == 1
    cleanup_districts.append(body["id"])


# ---------------------------------------------------------------------------
# parent_params: FK already validated upstream, not double-checked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_parent_params_not_double_checked(engine, seed, make_create_client, cleanup_districts):
    """`city_id` comes from the URL and is 404-validated by parent_params.

    The FK pre-flight must skip it. A valid URL → 201; bad URL → 404 from
    parent_params (not 422 from FK pre-flight).
    """
    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    async with await make_create_client(config) as client:
        bad = await client.post("/cities/9999/districts", json={"name": "X"})
        good = await client.post("/cities/1/districts", json={"name": "Y"})
    assert bad.status_code == 404
    assert good.status_code == 201, good.json()
    cleanup_districts.append(good.json()["id"])


# ---------------------------------------------------------------------------
# path_filters: URL-derived FK skipped by the pre-flight
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_path_filters_fk_skipped(engine, seed, make_create_client, cleanup_districts):
    """With path_filters mapping URL city_id → model field, the FK pre-flight
    skips that column. Valid URL → 201. (SQLite FK enforcement is off in tests,
    so even a bad URL wouldn't raise at commit — the point of this test is to
    confirm the pre-flight does NOT 422 on the URL-derived value.)"""
    config = CreateConfig(login_required=False)
    async with await make_create_client(
        config,
        path="/cities/{city_id}/districts",
        path_filters={"city_id": "city_id"},
        create_schema=DistrictCreateSchema,
    ) as client:
        r = await client.post("/cities/1/districts", json={"name": "PathFlt"})
    assert r.status_code == 201, r.json()
    assert r.json()["city_id"] == 1
    cleanup_districts.append(r.json()["id"])


# ---------------------------------------------------------------------------
# created_by_id: auto-set from current_user, skipped by the pre-flight
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_auto_set_created_by_id_skipped(engine, seed, cleanup_districts):
    """Even with a current_user whose id doesn't reference any User row,
    the pre-flight must NOT 422 because created_by_id is in skip_cols.
    (SQLite FK enforcement is off in tests, so commit also succeeds.)"""
    fake_user = User(id=9999, name="Ghost", company_id=None)
    app = _make_flat_app(engine, current_user=fake_user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/districts",
            json={"name": "Anon", "city_id": 1},
        )
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["created_by_id"] == 9999
    cleanup_districts.append(body["id"])


# ---------------------------------------------------------------------------
# Single-query verification: every pre-flight emits exactly one SELECT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_fk_check_uses_single_query(engine, seed, cleanup_districts):
    """The pre-flight must batch all FK checks into one round-trip."""
    calls: list[Any] = []
    orig_execute = AsyncSession.execute

    async def counting_execute(self, statement, *args, **kwargs):
        calls.append(statement)
        return await orig_execute(self, statement, *args, **kwargs)

    # Monkeypatch at the session class level so we capture every execute call
    # made by the handler — pre-flight + load + commit-time selects.
    import unittest.mock as mock
    with mock.patch.object(AsyncSession, "execute", counting_execute):
        app = _make_flat_app(engine)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post(
                "/districts",
                json={"name": "OneQuery", "city_id": 1, "company_id": 1},
            )
    assert r.status_code == 201, r.json()
    cleanup_districts.append(r.json()["id"])

    # Find the FK pre-flight SELECT: it's the one where the labeled columns
    # match our FK columns and there is NO FROM clause.
    from sqlalchemy.sql import Select
    fk_selects = []
    for stmt in calls:
        if not isinstance(stmt, Select):
            continue
        labels = {c.key for c in stmt.selected_columns}
        if labels == {"city_id", "company_id"}:
            fk_selects.append(stmt)
    assert len(fk_selects) == 1, (
        f"Expected exactly one FK pre-flight SELECT; got {len(fk_selects)}."
    )


# ---------------------------------------------------------------------------
# IntegrityError fallback: pre-flight defeated, commit fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_integrity_error_fallback(engine, seed, monkeypatch):
    """If the pre-flight is bypassed (e.g., the FK target is deleted between
    pre-flight and commit) and commit() raises IntegrityError, the chained
    translator must still produce a 422 (not 500).

    We simulate the race by patching `db.commit` to raise IntegrityError
    directly — SQLite has FK enforcement off in tests so we can't trigger a
    real FK violation at commit.
    """
    from sqlalchemy.exc import IntegrityError

    app = _make_flat_app(engine)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    # Override the get_db dependency to return a session whose commit raises.
    async def get_db_raising():
        async with session_factory() as session:
            orig_commit = session.commit

            async def fake_commit():
                raise IntegrityError("INSERT", {}, Exception("fk violation"))

            session.commit = fake_commit  # type: ignore[method-assign]
            try:
                yield session
            finally:
                session.commit = orig_commit  # type: ignore[method-assign]

    # Re-register with the failing session factory.
    app = FastAPI()

    async def get_current_user() -> Any:
        return None

    create_endpoint(
        router=app.router,
        path="/districts",
        model=District,
        create_schema=DistrictCreateFKSchema,
        read_schema=DistrictSchema,
        config=CreateConfig(login_required=False),
        login_dep=get_current_user,
        get_db=get_db_raising,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            "/districts",
            json={"name": "Race", "city_id": 1},
        )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["code"] == "VALIDATION_ERROR"
    assert detail["message"] == "Validation failed"
