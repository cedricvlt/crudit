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
# Permission checker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_permission_checker_denied_returns_403(seed, make_read_client):
    from tests.conftest import User

    user = User(id=1, name="Alice", tenant_id=1)

    def deny_all(current_user, permissions):
        return False

    config = ReadConfig(
        login_required=True,
        permissions=["core:district:view"],
        permission_checker=deny_all,
    )
    async with await make_read_client(config, current_user=user) as client:
        r = await client.get("/districts/1")
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_read_permission_checker_allowed_returns_200(seed, make_read_client):
    from tests.conftest import User

    user = User(id=1, name="Alice", tenant_id=1)

    def allow_all(current_user, permissions):
        return True

    config = ReadConfig(
        login_required=True,
        permissions=["core:district:view"],
        permission_checker=allow_all,
    )
    async with await make_read_client(config, current_user=user) as client:
        r = await client.get("/districts/1")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Tenant-level row permissions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_tenant_match_returns_200(seed, make_read_client):
    from tests.conftest import User

    user = User(id=1, name="Alice", tenant_id=1)
    async with await make_read_client(ReadConfig(login_required=True), current_user=user) as client:
        r = await client.get("/districts/1")  # district 1 has tenant_id=1
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_read_tenant_mismatch_returns_403(seed, make_read_client):
    from tests.conftest import User

    user = User(id=2, name="Bob", tenant_id=2)
    async with await make_read_client(ReadConfig(login_required=True), current_user=user) as client:
        r = await client.get("/districts/1")  # district 1 has tenant_id=1
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# Allowed-users row permissions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_explicit_user_access_overrides_tenant(seed, make_read_client):
    """
    User 3 (tenant_id=1) is in district 1's allowed_users.
    Even though tenant matches, this tests the explicit-user path.
    District 3 has tenant_id=2, user 3 has tenant_id=1 — tenant mismatch,
    but user 3 is NOT in district 3's allowed_users, so should be 403.
    """
    from tests.conftest import User

    user3 = User(id=3, name="Carol", tenant_id=1)
    async with await make_read_client(ReadConfig(login_required=True), current_user=user3) as client:
        # District 3 is tenant_id=2, user3 is tenant_id=1, not in allowed_users → 403
        r = await client.get("/districts/3")
        assert r.status_code == 403

        # District 1 is tenant_id=1, user3 is tenant_id=1 → tenant match → 200
        r = await client.get("/districts/1")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_before_query_hook(seed, make_read_client):
    calls = []

    def before(query, request, user):
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

    def after(row, request, user):
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

    async def before(query, request, user):
        log.append("before")
        return query

    async def after(row, request, user):
        log.append("after")
        return row

    async with await make_read_client(
        ReadConfig(login_required=False, before_query=before, after_query=after)
    ) as client:
        await client.get("/districts/1")
        assert log == ["before", "after"]
