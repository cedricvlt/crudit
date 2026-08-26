"""Ordered M2M links: ``M2MConfig(order_column=...)``.

Opting in makes the association column the source of truth for the list order,
appends freshly linked children after the existing ones, and registers
``POST {base_path}/reorder``.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from crudit import M2MConfig, m2m_router
from tests.conftest import District, User, district_allowed_users
from tests.m2m.conftest import UserSchema


async def _ids(client, path="/districts/2/users") -> list[int]:
    r = await client.get(path)
    assert r.status_code == 200
    return [u["id"] for u in r.json()]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_unknown_order_column_raises():
    with pytest.raises(ValueError, match="has no 'nope' column"):
        m2m_router(
            parent_model=District,
            child_model=User,
            association_table=district_allowed_users,
            child_schema=UserSchema,
            prefix="/districts",
            get_db=lambda: None,
            config=M2MConfig(order_column="nope"),
            mcp_expose=False,
        )


async def test_reorder_route_absent_when_unordered(seed, make_client):
    async with await make_client() as client:
        r = await client.post("/districts/2/users/reorder", json={"ids": [1]})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# List order / append on add
# ---------------------------------------------------------------------------


async def test_add_appends_after_existing_links(seed, make_client):
    async with await make_client(order_column="sort_order") as client:
        await client.post("/districts/2/users", json={"ids": [3, 1]})
        await client.post("/districts/2/users", json={"ids": [2]})
        assert await _ids(client) == [3, 1, 2]


async def test_add_returns_the_ordered_list(seed, make_client):
    async with await make_client(order_column="sort_order") as client:
        r = await client.post("/districts/2/users", json={"ids": [3, 2, 1]})
        assert [u["id"] for u in r.json()] == [3, 2, 1]


async def test_positions_start_after_preexisting_null_links(seed, make_client):
    # district 1 was linked to user3 by the seed, i.e. with a NULL sort_order.
    # Such rows sort last and must not collide with the appended ones.
    async with await make_client(order_column="sort_order") as client:
        await client.post("/districts/1/users", json={"ids": [1]})
        assert await _ids(client, "/districts/1/users") == [1, 3]


async def test_relinking_after_removal_moves_the_child_to_the_end(seed, make_client):
    async with await make_client(order_column="sort_order") as client:
        await client.post("/districts/2/users", json={"ids": [1, 2, 3]})
        await client.request("DELETE", "/districts/2/users", json={"ids": [1]})
        await client.post("/districts/2/users", json={"ids": [1]})
        assert await _ids(client) == [2, 3, 1]


# ---------------------------------------------------------------------------
# POST /districts/{district_id}/users/reorder
# ---------------------------------------------------------------------------


async def test_reorder_rewrites_positions(seed, make_client, db_session):
    async with await make_client(order_column="sort_order") as client:
        await client.post("/districts/2/users", json={"ids": [1, 2, 3]})
        r = await client.post("/districts/2/users/reorder", json={"ids": [3, 1, 2]})
        assert r.status_code == 204
        assert await _ids(client) == [3, 1, 2]

    rows = (
        await db_session.execute(
            select(
                district_allowed_users.c.user_id,
                district_allowed_users.c.sort_order,
            ).where(district_allowed_users.c.district_id == 2)
        )
    ).all()
    assert dict(rows) == {3: 0, 1: 1, 2: 2}


async def test_reorder_ignores_empty_payload(seed, make_client):
    async with await make_client(order_column="sort_order") as client:
        await client.post("/districts/2/users", json={"ids": [1, 2]})
        r = await client.post("/districts/2/users/reorder", json={"ids": []})
        assert r.status_code == 204
        assert await _ids(client) == [1, 2]


async def test_reorder_404_for_unlinked_child(seed, make_client):
    async with await make_client(order_column="sort_order") as client:
        await client.post("/districts/2/users", json={"ids": [1, 2]})
        r = await client.post("/districts/2/users/reorder", json={"ids": [2, 1, 3]})
        assert r.status_code == 404
        assert await _ids(client) == [1, 2]


async def test_reorder_404_for_nonexistent_parent(seed, make_client):
    async with await make_client(order_column="sort_order") as client:
        r = await client.post("/districts/999/users/reorder", json={"ids": [1]})
        assert r.status_code == 404


async def test_after_reorder_hook_receives_the_ordered_ids(seed, make_client):
    calls = []

    async def after_reorder(parent_id, child_ids, session, current_user):
        calls.append((parent_id, list(child_ids)))

    async with await make_client(
        order_column="sort_order", after_reorder=after_reorder
    ) as client:
        await client.post("/districts/2/users", json={"ids": [1, 2]})
        await client.post("/districts/2/users/reorder", json={"ids": [2, 1]})

    assert calls == [(2, [2, 1])]


async def test_after_reorder_not_called_for_empty_ids(seed, make_client):
    calls = []

    async def after_reorder(parent_id, child_ids, session, current_user):
        calls.append(child_ids)

    async with await make_client(
        order_column="sort_order", after_reorder=after_reorder
    ) as client:
        await client.post("/districts/2/users/reorder", json={"ids": []})

    assert calls == []
