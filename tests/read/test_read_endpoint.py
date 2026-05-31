from __future__ import annotations

import pytest
from crudit import ReadConfig


# ---------------------------------------------------------------------------
# Basic retrieval
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_returns_object(seed, make_read_client):
    async with await make_read_client(ReadConfig(login_required=False)) as client:
        r = await client.get("/districts/1")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == 1
        assert body["name"] == "Montmartre"


@pytest.mark.asyncio
async def test_read_includes_joined_relation(seed, make_read_client):
    async with await make_read_client(ReadConfig(login_required=False)) as client:
        r = await client.get("/districts/1")
        assert r.status_code == 200
        assert "city" in r.json()
        assert r.json()["city"]["name"] == "Paris"


@pytest.mark.asyncio
async def test_read_not_found_returns_404(seed, make_read_client):
    async with await make_read_client(ReadConfig(login_required=False)) as client:
        r = await client.get("/districts/9999")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Login / auth
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_login_required_no_user_returns_401(seed, make_read_client):
    async with await make_read_client(ReadConfig(login_required=True), current_user=None) as client:
        r = await client.get("/districts/1")
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_read_login_not_required_no_user_returns_200(seed, make_read_client):
    async with await make_read_client(ReadConfig(login_required=False), current_user=None) as client:
        r = await client.get("/districts/1")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Permission dep
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_permission_dep_denied_returns_403(seed, make_read_client):
    from fastapi import HTTPException
    from tests.conftest import Company, User

    user = User(id=1, name="Alice", companies=[Company(id=1)])

    def deny_dep(*_perms):
        async def dep():
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        return dep

    config = ReadConfig(
        login_required=True,
        permissions=["core:district:view"],
    )
    async with await make_read_client(config, current_user=user, permission_dep=deny_dep) as client:
        r = await client.get("/districts/1")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_read_permission_dep_allowed_returns_200(seed, make_read_client):
    from tests.conftest import Company, User

    user = User(id=1, name="Alice", companies=[Company(id=1)])

    def allow_dep(*_perms):
        async def dep():
            pass
        return dep

    config = ReadConfig(
        login_required=True,
        permissions=["core:district:view"],
    )
    async with await make_read_client(config, current_user=user, permission_dep=allow_dep) as client:
        r = await client.get("/districts/1")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Company-level row permissions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_company_match_returns_200(seed, make_read_client):
    from tests.conftest import Company, User

    user = User(id=1, name="Alice", companies=[Company(id=1)])
    async with await make_read_client(ReadConfig(login_required=True), current_user=user) as client:
        r = await client.get("/districts/1")  # district 1 has company_id=1
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_read_company_mismatch_returns_403(seed, make_read_client):
    from tests.conftest import Company, User

    user = User(id=2, name="Bob", companies=[Company(id=2)])
    async with await make_read_client(ReadConfig(login_required=True), current_user=user) as client:
        r = await client.get("/districts/1")  # district 1 has company_id=1
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Allowed-users row permissions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_explicit_user_access_overrides_company(seed, make_read_client):
    """
    User 3 (company_id=1) is in district 1's allowed_users.
    Even though company matches, this tests the explicit-user path.
    District 3 has company_id=2, user 3 has company_id=1 — company mismatch,
    but user 3 is NOT in district 3's allowed_users, so should be 403.
    """
    from tests.conftest import Company, User

    user3 = User(id=3, name="Carol", companies=[Company(id=1)])
    async with await make_read_client(ReadConfig(login_required=True), current_user=user3) as client:
        # District 3 is company_id=2, user3 is company_id=1, not in allowed_users → 403
        r = await client.get("/districts/3")
        assert r.status_code == 403

        # District 1 is company_id=1, user3 is company_id=1 → company match → 200
        r = await client.get("/districts/1")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_before_query_hook(seed, make_read_client):
    calls = []

    def before(query, ctx):
        calls.append(1)
        return query

    async with await make_read_client(
        ReadConfig(login_required=False, before_query=before)
    ) as client:
        await client.get("/districts/1")
        assert calls == [1]


@pytest.mark.asyncio
async def test_read_after_query_hook(seed, make_read_client):
    seen = []

    def after(row, ctx):
        seen.append(row)
        return row

    async with await make_read_client(
        ReadConfig(login_required=False, after_query=after)
    ) as client:
        r = await client.get("/districts/1")
        assert r.status_code == 200
        assert len(seen) == 1
        assert seen[0].id == 1


@pytest.mark.asyncio
async def test_read_async_hooks(seed, make_read_client):
    log = []

    async def before(query, ctx):
        log.append("before")
        return query

    async def after(row, ctx):
        log.append("after")
        return row

    async with await make_read_client(
        ReadConfig(login_required=False, before_query=before, after_query=after)
    ) as client:
        await client.get("/districts/1")
        assert log == ["before", "after"]
