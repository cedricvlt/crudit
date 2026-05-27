from __future__ import annotations

import pytest

from crudit import OptionsConfig


@pytest.mark.asyncio
async def test_login_required_no_user_returns_401(seed, make_client):
    async with await make_client(
        OptionsConfig(
            login_required=True,
        ),
        current_user=None,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_not_required_no_user_succeeds(seed, make_client):
    async with await make_client(
        OptionsConfig(
            login_required=False,
        ),
        current_user=None,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_permission_dep_deny(seed, make_client):
    from fastapi import HTTPException
    from tests.conftest import User

    def deny_dep(*_perms):
        async def dep():
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        return dep

    async with await make_client(
        OptionsConfig(
            login_required=True,
            permissions=["core:district:view"],
        ),
        current_user=User(id=1, name="Alice", company_id=1),
        permission_dep=deny_dep,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_permission_dep_allow(seed, make_client):
    from tests.conftest import User

    def allow_dep(*_perms):
        async def dep():
            pass
        return dep

    async with await make_client(
        OptionsConfig(
            login_required=True,
            permissions=["core:district:view"],
        ),
        current_user=User(id=1, name="Alice", company_id=1),
        permission_dep=allow_dep,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_company_row_level_filter(seed, make_client):
    from tests.conftest import User

    user1 = User(id=1, name="Alice", company_id=1)
    async with await make_client(
        OptionsConfig(
            login_required=True,
        ),
        current_user=user1,
    ) as client:
        # user1 is company 1 — only Paris districts (city_id=1) belong to company 1
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        ids = {d["id"] for d in r.json()["data"]}
        # districts 1 and 2 are company 1
        assert ids == {1, 2}


@pytest.mark.asyncio
async def test_allowed_users_row_level_filter(seed, make_client):
    from tests.conftest import User

    # user3 (company 1) is in allowed_users for district 1 only
    # but district 1 is also company 1, so company filter passes too
    user3 = User(id=3, name="Carol", company_id=1)
    async with await make_client(
        OptionsConfig(
            login_required=True,
        ),
        current_user=user3,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        # Both districts match company_id filter (company 1), so both visible
        assert r.json()["totalCount"] == 2
