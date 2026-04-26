from __future__ import annotations

import pytest

from crudit import OptionsConfig


@pytest.mark.asyncio
async def test_login_required_no_user_returns_401(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=True,
            label_field="name",
        ),
        current_user=None,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_not_required_no_user_succeeds(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
        ),
        current_user=None,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_permission_dep_deny(seed, make_client):
    from fastapi import Depends, HTTPException
    from tests.conftest import User

    def deny_dep(perms):
        async def check():
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        return Depends(check)

    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=True,
            label_field="name",
            permissions=["core:district:view"],
            permission_dep=deny_dep,
        ),
        current_user=User(id=1, name="Alice", tenant_id=1),
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_permission_dep_allow(seed, make_client):
    from fastapi import Depends
    from tests.conftest import User

    def allow_dep(perms):
        async def check():
            pass
        return Depends(check)

    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=True,
            label_field="name",
            permissions=["core:district:view"],
            permission_dep=allow_dep,
        ),
        current_user=User(id=1, name="Alice", tenant_id=1),
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_tenant_row_level_filter(seed, make_client):
    from tests.conftest import User

    user1 = User(id=1, name="Alice", tenant_id=1)
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=True,
            label_field="name",
        ),
        current_user=user1,
    ) as client:
        # user1 is tenant 1 — only Paris districts (city_id=1) belong to tenant 1
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        ids = {d["id"] for d in r.json()["data"]}
        # districts 1 and 2 are tenant 1
        assert ids == {1, 2}


@pytest.mark.asyncio
async def test_allowed_users_row_level_filter(seed, make_client):
    from tests.conftest import User

    # user3 (tenant 1) is in allowed_users for district 1 only
    # but district 1 is also tenant 1, so tenant filter passes too
    user3 = User(id=3, name="Carol", tenant_id=1)
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=True,
            label_field="name",
        ),
        current_user=user3,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        # Both districts match tenant_id filter (tenant 1), so both visible
        assert r.json()["total_count"] == 2
