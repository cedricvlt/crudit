from __future__ import annotations

import pytest

from crudit import CreateConfig, ParentParam
from tests.conftest import City, DistrictCreateFlatSchema, DistrictSchema, User


# ---------------------------------------------------------------------------
# Basic creation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_returns_201(seed, make_create_client, cleanup_districts):
    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    async with await make_create_client(config) as client:
        r = await client.post("/cities/1/districts", json={"name": "Pigalle"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Pigalle"
    assert body["is_active"] is True
    cleanup_districts.append(body["id"])


@pytest.mark.asyncio
async def test_create_sets_parent_fk(seed, make_create_client, cleanup_districts):
    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    async with await make_create_client(config) as client:
        r = await client.post("/cities/2/districts", json={"name": "Southbank"})
    assert r.status_code == 201
    assert r.json()["city_id"] == 2
    cleanup_districts.append(r.json()["id"])


@pytest.mark.asyncio
async def test_create_includes_joined_relation(seed, make_create_client, cleanup_districts):
    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    async with await make_create_client(config) as client:
        r = await client.post("/cities/1/districts", json={"name": "Belleville"})
    assert r.status_code == 201
    body = r.json()
    assert body["city"]["id"] == 1
    assert body["city"]["name"] == "Paris"
    cleanup_districts.append(body["id"])


# ---------------------------------------------------------------------------
# Parent existence check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_parent_not_found_returns_404(seed, make_create_client):
    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    async with await make_create_client(config) as client:
        r = await client.post("/cities/9999/districts", json={"name": "Ghost"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Login / auth
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_login_required_no_user_returns_401(seed, make_create_client):
    config = CreateConfig(
        login_required=True,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    async with await make_create_client(config, current_user=None) as client:
        r = await client.post("/cities/1/districts", json={"name": "Blocked"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_login_not_required_no_user_returns_201(seed, make_create_client, cleanup_districts):
    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    async with await make_create_client(config, current_user=None) as client:
        r = await client.post("/cities/1/districts", json={"name": "Open"})
    assert r.status_code == 201
    cleanup_districts.append(r.json()["id"])


# ---------------------------------------------------------------------------
# Permission dep
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_permission_dep_denied_returns_403(seed, make_create_client):
    from fastapi import HTTPException

    user = User(id=1, name="Alice", company_id=1)

    def deny_dep(*_perms):
        async def dep():
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        return dep

    config = CreateConfig(
        login_required=True,
        permissions=["core:district:edit"],
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    async with await make_create_client(config, current_user=user, permission_dep=deny_dep) as client:
        r = await client.post("/cities/1/districts", json={"name": "Denied"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_create_permission_dep_allowed_returns_201(seed, make_create_client, cleanup_districts):
    user = User(id=1, name="Alice", company_id=1)

    def allow_dep(*_perms):
        async def dep():
            pass
        return dep

    config = CreateConfig(
        login_required=True,
        permissions=["core:district:edit"],
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    async with await make_create_client(config, current_user=user, permission_dep=allow_dep) as client:
        r = await client.post("/cities/1/districts", json={"name": "Allowed"})
    assert r.status_code == 201
    cleanup_districts.append(r.json()["id"])


# ---------------------------------------------------------------------------
# Auto-complete: created_at and created_by
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_sets_created_at(seed, make_create_client, cleanup_districts):
    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    async with await make_create_client(config) as client:
        r = await client.post("/cities/1/districts", json={"name": "TimedDistrict"})
    assert r.status_code == 201
    assert r.json()["created_at"] is not None
    cleanup_districts.append(r.json()["id"])


@pytest.mark.asyncio
async def test_create_sets_created_by(seed, make_create_client, cleanup_districts):
    user = User(id=1, name="Alice", company_id=1)
    config = CreateConfig(
        login_required=True,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    async with await make_create_client(config, current_user=user) as client:
        r = await client.post("/cities/1/districts", json={"name": "ByAlice"})
    assert r.status_code == 201
    assert r.json()["created_by"] == 1
    cleanup_districts.append(r.json()["id"])


@pytest.mark.asyncio
async def test_create_created_by_not_set_without_user(seed, make_create_client, cleanup_districts):
    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    async with await make_create_client(config, current_user=None) as client:
        r = await client.post("/cities/1/districts", json={"name": "Anonymous"})
    assert r.status_code == 201
    assert r.json()["created_by"] is None
    cleanup_districts.append(r.json()["id"])


# ---------------------------------------------------------------------------
# Field setters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_field_setter(seed, make_create_client, cleanup_districts):
    def set_company(obj, request, user):
        return 1

    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
        field_setters={"company_id": set_company},
    )
    async with await make_create_client(config) as client:
        r = await client.post("/cities/1/districts", json={"name": "WithCompany"})
    assert r.status_code == 201
    cleanup_districts.append(r.json()["id"])


@pytest.mark.asyncio
async def test_create_async_field_setter(seed, make_create_client, cleanup_districts):
    async def set_company(obj, request, user):
        return 2

    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
        field_setters={"company_id": set_company},
    )
    async with await make_create_client(config) as client:
        r = await client.post("/cities/1/districts", json={"name": "AsyncCompany"})
    assert r.status_code == 201
    cleanup_districts.append(r.json()["id"])


@pytest.mark.asyncio
async def test_field_setter_receives_obj_request_user(seed, make_create_client, cleanup_districts):
    received = {}

    def capture(obj, request, user):
        received["name"] = obj.name
        received["method"] = request.method
        received["user"] = user
        return 1

    user = User(id=1, name="Alice", company_id=1)
    config = CreateConfig(
        login_required=True,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
        field_setters={"company_id": capture},
    )
    async with await make_create_client(config, current_user=user) as client:
        r = await client.post("/cities/1/districts", json={"name": "CaptureTest"})
    assert r.status_code == 201
    assert received["name"] == "CaptureTest"
    assert received["method"] == "POST"
    assert received["user"] is user
    cleanup_districts.append(r.json()["id"])


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_before_create_hook(seed, make_create_client, cleanup_districts):
    calls = []

    def before(obj, request, user):
        calls.append(obj.name)
        obj.name = obj.name.upper()
        return obj

    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
        before_create=before,
    )
    async with await make_create_client(config) as client:
        r = await client.post("/cities/1/districts", json={"name": "hookme"})
    assert r.status_code == 201
    assert r.json()["name"] == "HOOKME"
    assert calls == ["hookme"]
    cleanup_districts.append(r.json()["id"])


@pytest.mark.asyncio
async def test_create_after_create_hook(seed, make_create_client, cleanup_districts):
    seen_ids = []

    def after(obj, request, user):
        seen_ids.append(obj.id)
        return obj

    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
        after_create=after,
    )
    async with await make_create_client(config) as client:
        r = await client.post("/cities/1/districts", json={"name": "AfterHook"})
    assert r.status_code == 201
    assert len(seen_ids) == 1
    assert seen_ids[0] == r.json()["id"]
    cleanup_districts.append(r.json()["id"])


@pytest.mark.asyncio
async def test_create_async_hooks(seed, make_create_client, cleanup_districts):
    log = []

    async def before(obj, request, user):
        log.append("before")
        return obj

    async def after(obj, request, user):
        log.append("after")
        return obj

    config = CreateConfig(
        login_required=False,
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
        before_create=before,
        after_create=after,
    )
    async with await make_create_client(config) as client:
        r = await client.post("/cities/1/districts", json={"name": "AsyncHooks"})
    assert r.status_code == 201
    assert log == ["before", "after"]
    cleanup_districts.append(r.json()["id"])


# ---------------------------------------------------------------------------
# No parent_params (flat resource)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_without_parent_flat(seed, cleanup_districts, engine):
    """Flat create using a schema that includes city_id in the body."""
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from crudit import create_endpoint

    app = FastAPI()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def get_user():
        return None

    cfg = CreateConfig(login_required=False)

    create_endpoint(
        router=app.router,
        path="/districts",
        model=__import__("tests.conftest", fromlist=["District"]).District,
        create_schema=DistrictCreateFlatSchema,
        read_schema=DistrictSchema,
        config=cfg,
        login_dep=get_user,
        get_db=get_db,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/districts", json={"name": "Flat", "city_id": 1})
    assert r.status_code == 201
    assert r.json()["city_id"] == 1
    cleanup_districts.append(r.json()["id"])


# ---------------------------------------------------------------------------
# path_filters — lighter-weight than parent_params
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_with_path_filters_injects_value(
    seed, make_create_client, cleanup_districts
):
    """path_filters should auto-set the model field from the URL param even
    when the create schema does not include the field."""
    cfg = CreateConfig(login_required=False)
    async with await make_create_client(
        cfg,
        path_filters={"city_id": "city_id"},
    ) as client:
        r = await client.post("/cities/2/districts", json={"name": "Pigalle"})
    assert r.status_code == 201
    body = r.json()
    assert body["city_id"] == 2
    cleanup_districts.append(body["id"])


@pytest.mark.asyncio
async def test_create_with_path_filters_strips_field_from_flat_schema(
    seed, make_create_client, cleanup_districts
):
    """When the create schema declares the path_filter field, the body must
    not require it — the URL value wins, and a request body that includes it
    is rejected as an unknown field."""
    cfg = CreateConfig(login_required=False)
    async with await make_create_client(
        cfg,
        path_filters={"city_id": "city_id"},
        create_schema=DistrictCreateFlatSchema,
    ) as client:
        # Body omits city_id — value is read from the URL.
        r = await client.post("/cities/1/districts", json={"name": "Belleville"})
    assert r.status_code == 201
    assert r.json()["city_id"] == 1
    cleanup_districts.append(r.json()["id"])


@pytest.mark.asyncio
async def test_create_with_path_filters_url_overrides_body(
    seed, make_create_client, cleanup_districts
):
    """Even if the client sneaks a value into the body, the URL wins and the
    extra field is ignored (it has been stripped from the body schema)."""
    cfg = CreateConfig(login_required=False)
    async with await make_create_client(
        cfg,
        path_filters={"city_id": "city_id"},
        create_schema=DistrictCreateFlatSchema,
    ) as client:
        r = await client.post(
            "/cities/1/districts",
            json={"name": "Marais 2", "city_id": 2},
        )
    assert r.status_code == 201
    assert r.json()["city_id"] == 1  # URL value, not body value
    cleanup_districts.append(r.json()["id"])
