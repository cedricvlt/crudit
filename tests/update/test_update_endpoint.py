from __future__ import annotations

import pytest

from crudit import UpdateConfig
from tests.conftest import User


# ---------------------------------------------------------------------------
# Basic update
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_returns_200(seed, make_update_client):
    config = UpdateConfig(login_required=False)
    async with await make_update_client(config) as client:
        r = await client.patch("/districts/1", json={"name": "Renamed"})
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed"
    assert r.json()["id"] == 1


@pytest.mark.asyncio
async def test_update_partial_only_changes_sent_fields(seed, make_update_client):
    config = UpdateConfig(login_required=False)
    async with await make_update_client(config) as client:
        r = await client.patch("/districts/1", json={"name": "PartialUpdate"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "PartialUpdate"
    # is_active was not sent — must retain its original value
    assert body["is_active"] is True


@pytest.mark.asyncio
async def test_update_includes_joined_relation(seed, make_update_client):
    config = UpdateConfig(login_required=False)
    async with await make_update_client(config) as client:
        r = await client.patch("/districts/1", json={"name": "WithJoin"})
    assert r.status_code == 200
    body = r.json()
    assert "city" in body
    assert body["city"]["name"] == "Paris"


@pytest.mark.asyncio
async def test_update_not_found_returns_404(seed, make_update_client):
    config = UpdateConfig(login_required=False)
    async with await make_update_client(config) as client:
        r = await client.patch("/districts/9999", json={"name": "Ghost"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Login / auth
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_login_required_no_user_returns_401(seed, make_update_client):
    config = UpdateConfig(login_required=True)
    async with await make_update_client(config, current_user=None) as client:
        r = await client.patch("/districts/1", json={"name": "Blocked"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_update_login_not_required_no_user_returns_200(seed, make_update_client):
    config = UpdateConfig(login_required=False)
    async with await make_update_client(config, current_user=None) as client:
        r = await client.patch("/districts/1", json={"name": "Open"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Permission checker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_permission_checker_denied_returns_403(seed, make_update_client):
    user = User(id=1, name="Alice", tenant_id=1)

    def deny_all(current_user, permissions):
        return False

    config = UpdateConfig(
        login_required=True,
        permissions=["core:district:edit"],
        permission_checker=deny_all,
    )
    async with await make_update_client(config, current_user=user) as client:
        r = await client.patch("/districts/1", json={"name": "Denied"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_update_permission_checker_allowed_returns_200(seed, make_update_client):
    user = User(id=1, name="Alice", tenant_id=1)

    def allow_all(current_user, permissions):
        return True

    config = UpdateConfig(
        login_required=True,
        permissions=["core:district:edit"],
        permission_checker=allow_all,
    )
    async with await make_update_client(config, current_user=user) as client:
        r = await client.patch("/districts/1", json={"name": "Allowed"})
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Tenant row-level permissions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_tenant_match_returns_200(seed, make_update_client):
    user = User(id=1, name="Alice", tenant_id=1)
    config = UpdateConfig(login_required=True)
    async with await make_update_client(config, current_user=user) as client:
        r = await client.patch("/districts/1", json={"name": "TenantOK"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_update_tenant_mismatch_returns_403(seed, make_update_client):
    user = User(id=2, name="Bob", tenant_id=2)
    config = UpdateConfig(login_required=True)
    async with await make_update_client(config, current_user=user) as client:
        # district 1 has tenant_id=1, user has tenant_id=2
        r = await client.patch("/districts/1", json={"name": "WrongTenant"})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Auto-complete: updated_at and updated_by
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_sets_updated_at(seed, make_update_client):
    config = UpdateConfig(login_required=False)
    async with await make_update_client(config) as client:
        r = await client.patch("/districts/1", json={"name": "Timed"})
    assert r.status_code == 200
    assert r.json()["updated_at"] is not None


@pytest.mark.asyncio
async def test_update_sets_updated_by(seed, make_update_client):
    user = User(id=1, name="Alice", tenant_id=1)
    config = UpdateConfig(login_required=True)
    async with await make_update_client(config, current_user=user) as client:
        r = await client.patch("/districts/1", json={"name": "ByAlice"})
    assert r.status_code == 200
    assert r.json()["updated_by"] == 1


@pytest.mark.asyncio
async def test_update_updated_by_not_set_without_user(seed, make_update_client):
    config = UpdateConfig(login_required=False)
    async with await make_update_client(config, current_user=None) as client:
        r = await client.patch("/districts/1", json={"name": "Anon"})
    assert r.status_code == 200
    assert r.json()["updated_by"] is None


# ---------------------------------------------------------------------------
# Field setters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_field_setter(seed, make_update_client):
    def mark_tenant(obj, request, user):
        return 1

    config = UpdateConfig(
        login_required=False,
        field_setters={"tenant_id": mark_tenant},
    )
    async with await make_update_client(config) as client:
        r = await client.patch("/districts/3", json={"name": "SetterApplied"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_update_async_field_setter(seed, make_update_client):
    async def mark_tenant(obj, request, user):
        return 1

    config = UpdateConfig(
        login_required=False,
        field_setters={"tenant_id": mark_tenant},
    )
    async with await make_update_client(config) as client:
        r = await client.patch("/districts/3", json={"name": "AsyncSetter"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_field_setter_receives_obj_request_user(seed, make_update_client):
    received = {}

    def capture(obj, request, user):
        received["name"] = obj.name
        received["method"] = request.method
        received["user"] = user
        return 1

    user = User(id=1, name="Alice", tenant_id=1)
    config = UpdateConfig(
        login_required=True,
        field_setters={"tenant_id": capture},
    )
    async with await make_update_client(config, current_user=user) as client:
        r = await client.patch("/districts/1", json={"name": "CaptureTest"})
    assert r.status_code == 200
    # obj.name is the pre-update value at setter time
    assert received["method"] == "PATCH"
    assert received["user"] is user


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_before_update_hook_receives_obj_and_patch(seed, make_update_client):
    captured = {}

    def before(obj, patch_data, request, user):
        captured["original_name"] = obj.name
        captured["patch_keys"] = list(patch_data.keys())
        return patch_data

    config = UpdateConfig(login_required=False, before_update=before)
    async with await make_update_client(config) as client:
        r = await client.patch("/districts/1", json={"name": "HookTest"})
    assert r.status_code == 200
    assert captured["original_name"] == "Montmartre"
    assert "name" in captured["patch_keys"]


@pytest.mark.asyncio
async def test_update_before_update_hook_can_modify_patch(seed, make_update_client):
    def uppercase_name(obj, patch_data, request, user):
        if "name" in patch_data:
            patch_data["name"] = patch_data["name"].upper()
        return patch_data

    config = UpdateConfig(login_required=False, before_update=uppercase_name)
    async with await make_update_client(config) as client:
        r = await client.patch("/districts/1", json={"name": "lowercase"})
    assert r.status_code == 200
    assert r.json()["name"] == "LOWERCASE"


@pytest.mark.asyncio
async def test_update_after_update_hook(seed, make_update_client):
    seen_ids = []

    def after(obj, request, user):
        seen_ids.append(obj.id)
        return obj

    config = UpdateConfig(login_required=False, after_update=after)
    async with await make_update_client(config) as client:
        r = await client.patch("/districts/1", json={"name": "AfterHook"})
    assert r.status_code == 200
    assert seen_ids == [1]


@pytest.mark.asyncio
async def test_update_async_hooks(seed, make_update_client):
    log = []

    async def before(obj, patch_data, request, user):
        log.append("before")
        return patch_data

    async def after(obj, request, user):
        log.append("after")
        return obj

    config = UpdateConfig(
        login_required=False,
        before_update=before,
        after_update=after,
    )
    async with await make_update_client(config) as client:
        r = await client.patch("/districts/1", json={"name": "AsyncHooks"})
    assert r.status_code == 200
    assert log == ["before", "after"]
