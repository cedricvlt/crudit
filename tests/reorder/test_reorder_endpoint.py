from __future__ import annotations

import pytest
from fastapi import APIRouter
from sqlalchemy import Column, Integer
from sqlalchemy.orm import DeclarativeBase

from crudit import ReorderConfig, reorder_endpoint
from tests.conftest import User
from tests.reorder.conftest import get_sort_order


class _NoSortOrderBase(DeclarativeBase):
    pass


class _NoSortOrder(_NoSortOrderBase):
    __tablename__ = "no_sort_order_validation"
    id = Column(Integer, primary_key=True)


# ---------------------------------------------------------------------------
# Basic reorder
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reorder_returns_204(seed, make_reorder_client):
    config = ReorderConfig(login_required=False)
    async with await make_reorder_client(config) as client:
        r = await client.post("/districts/reorder", json={"ids": [2, 1]})
    assert r.status_code == 204
    assert r.content == b""


@pytest.mark.asyncio
async def test_reorder_assigns_sort_order_by_position(seed, make_reorder_client, engine):
    config = ReorderConfig(login_required=False)
    async with await make_reorder_client(config) as client:
        r = await client.post("/districts/reorder", json={"ids": [2, 1, 4, 3]})
    assert r.status_code == 204
    assert await get_sort_order(engine, 2) == 0
    assert await get_sort_order(engine, 1) == 1
    assert await get_sort_order(engine, 4) == 2
    assert await get_sort_order(engine, 3) == 3


@pytest.mark.asyncio
async def test_reorder_partial_list_only_updates_provided(seed, make_reorder_client, engine):
    config = ReorderConfig(login_required=False)
    async with await make_reorder_client(config) as client:
        r = await client.post("/districts/reorder", json={"ids": [3, 1]})
    assert r.status_code == 204
    assert await get_sort_order(engine, 3) == 0
    assert await get_sort_order(engine, 1) == 1
    # districts 2 and 4 were not provided — sort_order unchanged (None)
    assert await get_sort_order(engine, 2) is None
    assert await get_sort_order(engine, 4) is None


@pytest.mark.asyncio
async def test_reorder_empty_ids_returns_204(seed, make_reorder_client):
    config = ReorderConfig(login_required=False)
    async with await make_reorder_client(config) as client:
        r = await client.post("/districts/reorder", json={"ids": []})
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# Unknown ID
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reorder_unknown_id_returns_404(seed, make_reorder_client):
    config = ReorderConfig(login_required=False)
    async with await make_reorder_client(config) as client:
        r = await client.post("/districts/reorder", json={"ids": [1, 9999]})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Login / auth
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reorder_login_required_no_user_returns_401(seed, make_reorder_client):
    config = ReorderConfig(login_required=True)
    async with await make_reorder_client(config, current_user=None) as client:
        r = await client.post("/districts/reorder", json={"ids": [1, 2]})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_reorder_login_not_required_no_user_returns_204(seed, make_reorder_client):
    config = ReorderConfig(login_required=False)
    async with await make_reorder_client(config, current_user=None) as client:
        r = await client.post("/districts/reorder", json={"ids": [1, 2]})
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# Permission dep
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reorder_permission_dep_denied_returns_403(seed, make_reorder_client):
    from fastapi import HTTPException

    user = User(id=1, name="Alice", tenant_id=1)

    def deny_dep(*_perms):
        async def dep():
            raise HTTPException(status_code=403, detail="Insufficient permissions.")
        return dep

    config = ReorderConfig(
        login_required=True,
        permissions=["core:district:edit"],
    )
    async with await make_reorder_client(config, current_user=user, permission_dep=deny_dep) as client:
        r = await client.post("/districts/reorder", json={"ids": [1, 2]})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reorder_permission_dep_allowed_returns_204(seed, make_reorder_client):
    user = User(id=1, name="Alice", tenant_id=1)

    def allow_dep(*_perms):
        async def dep():
            pass
        return dep

    config = ReorderConfig(
        login_required=True,
        permissions=["core:district:edit"],
    )
    async with await make_reorder_client(config, current_user=user, permission_dep=allow_dep) as client:
        r = await client.post("/districts/reorder", json={"ids": [1, 2]})
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# Row-level permissions — tenant_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reorder_wrong_tenant_returns_403(seed, make_reorder_client):
    # district 3 has tenant_id=2; user has tenant_id=1
    user = User(id=1, name="Alice", tenant_id=1)
    config = ReorderConfig(login_required=True)
    async with await make_reorder_client(config, current_user=user) as client:
        r = await client.post("/districts/reorder", json={"ids": [1, 3]})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_reorder_correct_tenant_returns_204(seed, make_reorder_client, engine):
    # districts 1 and 2 both have tenant_id=1; user has tenant_id=1
    user = User(id=1, name="Alice", tenant_id=1)
    config = ReorderConfig(login_required=True)
    async with await make_reorder_client(config, current_user=user) as client:
        r = await client.post("/districts/reorder", json={"ids": [2, 1]})
    assert r.status_code == 204
    assert await get_sort_order(engine, 2) == 0
    assert await get_sort_order(engine, 1) == 1


# ---------------------------------------------------------------------------
# Row-level permissions — allowed_users
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reorder_via_allowed_users_returns_204(seed, make_reorder_client, engine):
    # district 1 has tenant_id=1 and user3 (tenant_id=1) is in allowed_users
    user3 = User(id=3, name="Carol", tenant_id=1)
    config = ReorderConfig(login_required=True)
    async with await make_reorder_client(config, current_user=user3) as client:
        r = await client.post("/districts/reorder", json={"ids": [2, 1]})
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_reorder_not_in_allowed_users_wrong_tenant_returns_403(seed, make_reorder_client):
    # user2 (tenant_id=2) is NOT in district 1's allowed_users and tenant doesn't match
    user2 = User(id=2, name="Bob", tenant_id=2)
    config = ReorderConfig(login_required=True)
    async with await make_reorder_client(config, current_user=user2) as client:
        r = await client.post("/districts/reorder", json={"ids": [1, 2]})
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Path filters
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reorder_path_filter_scopes_query(seed, make_reorder_client, engine):
    # districts 1 and 2 are in city_id=1
    config = ReorderConfig(
        login_required=False,
        path_filters={"city_id": "city_id"},
    )
    async with await make_reorder_client(
        config, path="/cities/{city_id}/districts/reorder"
    ) as client:
        r = await client.post("/cities/1/districts/reorder", json={"ids": [2, 1]})
    assert r.status_code == 204
    assert await get_sort_order(engine, 2) == 0
    assert await get_sort_order(engine, 1) == 1


@pytest.mark.asyncio
async def test_reorder_path_filter_excludes_other_scope(seed, make_reorder_client):
    # district 3 is in city_id=2, not city_id=1 — should 404
    config = ReorderConfig(
        login_required=False,
        path_filters={"city_id": "city_id"},
    )
    async with await make_reorder_client(
        config, path="/cities/{city_id}/districts/reorder"
    ) as client:
        r = await client.post("/cities/1/districts/reorder", json={"ids": [1, 3]})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reorder_before_hook_receives_objects(seed, make_reorder_client):
    captured = []

    def before(objects, request, user):
        captured.extend(obj.id for obj in objects)

    config = ReorderConfig(login_required=False, before_reorder=before)
    async with await make_reorder_client(config) as client:
        r = await client.post("/districts/reorder", json={"ids": [2, 1]})
    assert r.status_code == 204
    assert captured == [2, 1]


@pytest.mark.asyncio
async def test_reorder_after_hook_receives_objects_with_new_positions(
    seed, make_reorder_client
):
    captured = {}

    def after(objects, request, user):
        for obj in objects:
            captured[obj.id] = obj.sort_order

    config = ReorderConfig(login_required=False, after_reorder=after)
    async with await make_reorder_client(config) as client:
        r = await client.post("/districts/reorder", json={"ids": [2, 1]})
    assert r.status_code == 204
    assert captured == {2: 0, 1: 1}


@pytest.mark.asyncio
async def test_reorder_async_hooks(seed, make_reorder_client):
    log = []

    async def before(objects, request, user):
        log.append("before")

    async def after(objects, request, user):
        log.append("after")

    config = ReorderConfig(
        login_required=False, before_reorder=before, after_reorder=after
    )
    async with await make_reorder_client(config) as client:
        r = await client.post("/districts/reorder", json={"ids": [1, 2]})
    assert r.status_code == 204
    assert log == ["before", "after"]


@pytest.mark.asyncio
async def test_reorder_before_hook_can_abort(seed, make_reorder_client, engine):
    from fastapi import HTTPException

    def before(objects, request, user):
        raise HTTPException(status_code=409, detail="Cannot reorder: locked.")

    config = ReorderConfig(login_required=False, before_reorder=before)
    async with await make_reorder_client(config) as client:
        r = await client.post("/districts/reorder", json={"ids": [2, 1]})
    assert r.status_code == 409
    # sort_order unchanged — commit never happened
    assert await get_sort_order(engine, 1) is None
    assert await get_sort_order(engine, 2) is None


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def test_reorder_endpoint_raises_if_no_sort_order_column():
    with pytest.raises(ValueError, match="sort_order"):
        reorder_endpoint(
            router=APIRouter(),
            path="/items/reorder",
            model=_NoSortOrder,
            config=ReorderConfig(login_required=False),
            get_db=lambda: None,
        )
