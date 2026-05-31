from __future__ import annotations

import pytest

from crudit import DeleteConfig
from tests.conftest import Company, User
from tests.delete.conftest import district_exists


# ---------------------------------------------------------------------------
# Basic deletion
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_returns_204(delete_target, make_delete_client, engine):
    config = DeleteConfig(login_required=False)
    async with await make_delete_client(config) as client:
        r = await client.delete("/districts/100")
    assert r.status_code == 204
    assert r.content == b""
    assert not await district_exists(engine, 100)


@pytest.mark.asyncio
async def test_delete_not_found_returns_404(seed, make_delete_client):
    config = DeleteConfig(login_required=False)
    async with await make_delete_client(config) as client:
        r = await client.delete("/districts/9999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Login / auth
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_login_required_no_user_returns_401(seed, make_delete_client):
    # district 1 is never deleted — seed teardown is safe
    config = DeleteConfig(login_required=True)
    async with await make_delete_client(config, current_user=None) as client:
        r = await client.delete("/districts/1")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_delete_login_not_required_no_user_returns_204(delete_target, make_delete_client, engine):
    config = DeleteConfig(login_required=False)
    async with await make_delete_client(config, current_user=None) as client:
        r = await client.delete("/districts/100")
    assert r.status_code == 204
    assert not await district_exists(engine, 100)


# ---------------------------------------------------------------------------
# Permission dep
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_permission_dep_denied_returns_403(seed, make_delete_client):
    from fastapi import HTTPException

    user = User(id=1, name="Alice", companies=[Company(id=1)])

    def deny_dep(*_perms):
        async def dep():
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        return dep

    config = DeleteConfig(
        login_required=True,
        permissions=["core:district:delete"],
    )
    async with await make_delete_client(config, current_user=user, permission_dep=deny_dep) as client:
        r = await client.delete("/districts/1")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_permission_dep_allowed_returns_204(delete_target, make_delete_client, engine):
    user = User(id=1, name="Alice", companies=[Company(id=1)])

    def allow_dep(*_perms):
        async def dep():
            pass
        return dep

    config = DeleteConfig(
        login_required=True,
        permissions=["core:district:delete"],
    )
    async with await make_delete_client(config, current_user=user, permission_dep=allow_dep) as client:
        r = await client.delete("/districts/100")
    assert r.status_code == 204
    assert not await district_exists(engine, 100)


# ---------------------------------------------------------------------------
# Row-level permissions — company_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_wrong_company_returns_403(seed, make_delete_client):
    # district 3 has company_id=2; user has company_id=1 — mismatch, no allowed_users
    user = User(id=1, name="Alice", companies=[Company(id=1)])
    config = DeleteConfig(login_required=True)
    async with await make_delete_client(config, current_user=user) as client:
        r = await client.delete("/districts/3")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_correct_company_returns_204(delete_target, make_delete_client, engine):
    # delete_target has company_id=1; user has company_id=1
    user = User(id=1, name="Alice", companies=[Company(id=1)])
    config = DeleteConfig(login_required=True)
    async with await make_delete_client(config, current_user=user) as client:
        r = await client.delete("/districts/100")
    assert r.status_code == 204
    assert not await district_exists(engine, 100)


# ---------------------------------------------------------------------------
# Row-level permissions — allowed_users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_not_in_allowed_users_wrong_company_returns_403(seed, make_delete_client):
    # user2 (company_id=2) is NOT in district 1's allowed_users and company doesn't match
    user2 = User(id=2, name="Bob", companies=[Company(id=2)])
    config = DeleteConfig(login_required=True)
    async with await make_delete_client(config, current_user=user2) as client:
        r = await client.delete("/districts/1")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_via_allowed_users_returns_204(
    delete_target_allowed_user, make_delete_client, engine
):
    # district 101 has company_id=2; user3 has company_id=1 but is in allowed_users
    user3 = User(id=3, name="Carol", companies=[Company(id=1)])
    config = DeleteConfig(login_required=True)
    async with await make_delete_client(config, current_user=user3) as client:
        r = await client.delete("/districts/101")
    assert r.status_code == 204
    assert not await district_exists(engine, 101)


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_before_hook_receives_obj(delete_target, make_delete_client):
    captured = {}

    def before(obj, request, user):
        captured["id"] = obj.id
        captured["name"] = obj.name

    config = DeleteConfig(login_required=False, before_delete=before)
    async with await make_delete_client(config) as client:
        r = await client.delete("/districts/100")
    assert r.status_code == 204
    assert captured == {"id": 100, "name": "ToDelete"}


@pytest.mark.asyncio
async def test_delete_after_hook_receives_obj(delete_target, make_delete_client, engine):
    captured = {}

    def after(obj, request, user):
        captured["id"] = obj.id
        captured["name"] = obj.name

    config = DeleteConfig(login_required=False, after_delete=after)
    async with await make_delete_client(config) as client:
        r = await client.delete("/districts/100")
    assert r.status_code == 204
    assert captured == {"id": 100, "name": "ToDelete"}
    assert not await district_exists(engine, 100)


@pytest.mark.asyncio
async def test_delete_async_hooks(delete_target, make_delete_client):
    log = []

    async def before(obj, request, user):
        log.append("before")

    async def after(obj, request, user):
        log.append("after")

    config = DeleteConfig(login_required=False, before_delete=before, after_delete=after)
    async with await make_delete_client(config) as client:
        r = await client.delete("/districts/100")
    assert r.status_code == 204
    assert log == ["before", "after"]


@pytest.mark.asyncio
async def test_delete_before_hook_can_abort(delete_target, make_delete_client, engine):
    from fastapi import HTTPException

    def before(obj, request, user):
        raise HTTPException(status_code=409, detail="Cannot delete: referenced elsewhere.")

    config = DeleteConfig(login_required=False, before_delete=before)
    async with await make_delete_client(config) as client:
        r = await client.delete("/districts/100")
    assert r.status_code == 409
    assert await district_exists(engine, 100)
