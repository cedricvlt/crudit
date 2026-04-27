from __future__ import annotations

import pytest
from crudit import ListConfig


@pytest.mark.asyncio
async def test_unauthenticated_returns_401(seed, make_client):
    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            login_required=True,
        ),
        current_user=None,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_no_login_required(seed, make_client):
    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
        ),
        current_user=None,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_tenant_filter_isolates_rows(seed, make_client):
    from tests.conftest import User
    user = User(id=1, name="Alice", tenant_id=1)

    async with await make_client(
        ListConfig(
            path_filters={},
            login_required=True,
        ),
        current_user=user,
    ) as client:
        # Districts for all cities — tenant_id=1 has Montmartre & Marais (city 1)
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        data = r.json()["data"]
        assert all(d["city_id"] == 1 for d in data)
        # Downtown and Uptown (tenant_id=2) should not appear
        names = {d["name"] for d in data}
        assert "Downtown" not in names
        assert "Uptown" not in names


@pytest.mark.asyncio
async def test_allowed_users_grants_access(seed, make_client):
    """user3 (tenant_id=1) is in allowed_users for district 1 (tenant_id=1).
    Since they share a tenant, they still see tenant-matching rows."""
    from tests.conftest import User
    user3 = User(id=3, name="Carol", tenant_id=1)

    async with await make_client(
        ListConfig(
            path_filters={},
            login_required=True,
        ),
        current_user=user3,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) > 0


@pytest.mark.asyncio
async def test_permission_dep_forbidden(seed, make_client):
    from fastapi import HTTPException
    from tests.conftest import User

    async def deny_dep():
        raise HTTPException(status_code=403, detail="Insufficient permissions.")

    user = User(id=1, name="Alice", tenant_id=1)

    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            login_required=True,
            permissions=["core:district:view"],
        ),
        current_user=user,
        permission_dep=deny_dep,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_permission_dep_allowed(seed, make_client):
    from tests.conftest import User

    async def allow_dep():
        pass

    user = User(id=1, name="Alice", tenant_id=1)

    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            login_required=True,
            permissions=["core:district:view"],
        ),
        current_user=user,
        permission_dep=allow_dep,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
