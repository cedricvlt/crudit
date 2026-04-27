from __future__ import annotations

from fastapi import HTTPException


# ---------------------------------------------------------------------------
# GET /districts/{district_id}/users
# ---------------------------------------------------------------------------


async def test_list_returns_linked_users(seed, make_client):
    # district 1 has user3 (Carol) linked via district_allowed_users in conftest seed
    async with await make_client() as client:
        r = await client.get("/districts/1/users")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        ids = {u["id"] for u in data}
        assert 3 in ids  # Carol


async def test_list_empty_for_district_with_no_links(seed, make_client):
    async with await make_client() as client:
        r = await client.get("/districts/2/users")
        assert r.status_code == 200
        assert r.json() == []


async def test_list_404_for_nonexistent_parent(seed, make_client):
    async with await make_client() as client:
        r = await client.get("/districts/999/users")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /districts/{district_id}/users  (add)
# ---------------------------------------------------------------------------


async def test_add_links_users_and_returns_list(seed, make_client):
    async with await make_client() as client:
        # district 2 has no users; add user1 and user2
        r = await client.post("/districts/2/users", json={"ids": [1, 2]})
        assert r.status_code == 200
        ids = {u["id"] for u in r.json()}
        assert {1, 2} <= ids


async def test_add_is_idempotent(seed, make_client):
    async with await make_client() as client:
        r1 = await client.post("/districts/2/users", json={"ids": [1]})
        r2 = await client.post("/districts/2/users", json={"ids": [1]})
        assert r1.status_code == 200
        assert r2.status_code == 200
        # user appears only once in the returned list
        ids = [u["id"] for u in r2.json()]
        assert ids.count(1) == 1


async def test_add_empty_ids_is_noop(seed, make_client):
    async with await make_client() as client:
        r = await client.post("/districts/1/users", json={"ids": []})
        assert r.status_code == 200
        # district 1 still has Carol (user3)
        ids = {u["id"] for u in r.json()}
        assert 3 in ids


async def test_add_422_for_nonexistent_child_id(seed, make_client):
    async with await make_client() as client:
        r = await client.post("/districts/1/users", json={"ids": [9999]})
        assert r.status_code == 422


async def test_add_404_for_nonexistent_parent(seed, make_client):
    async with await make_client() as client:
        r = await client.post("/districts/999/users", json={"ids": [1]})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /districts/{district_id}/users  (remove)
# ---------------------------------------------------------------------------


async def test_remove_unlinks_users(seed, make_client):
    async with await make_client() as client:
        # first add user1 to district 1
        await client.post("/districts/1/users", json={"ids": [1]})
        r_before = await client.get("/districts/1/users")
        assert any(u["id"] == 1 for u in r_before.json())

        # now remove user1
        r = await client.request("DELETE", "/districts/1/users", json={"ids": [1]})
        assert r.status_code == 204

        r_after = await client.get("/districts/1/users")
        assert not any(u["id"] == 1 for u in r_after.json())


async def test_remove_is_idempotent(seed, make_client):
    async with await make_client() as client:
        r1 = await client.request("DELETE", "/districts/1/users", json={"ids": [999]})
        r2 = await client.request("DELETE", "/districts/1/users", json={"ids": [999]})
        assert r1.status_code == 204
        assert r2.status_code == 204


async def test_remove_empty_ids_is_noop(seed, make_client):
    async with await make_client() as client:
        r = await client.request("DELETE", "/districts/1/users", json={"ids": []})
        assert r.status_code == 204


async def test_remove_404_for_nonexistent_parent(seed, make_client):
    async with await make_client() as client:
        r = await client.request("DELETE", "/districts/999/users", json={"ids": [1]})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Authentication (login_dep)
# ---------------------------------------------------------------------------


async def test_login_dep_enforced_when_login_required(seed, make_client):
    async def require_auth():
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with await make_client(login_dep=require_auth, login_required=True) as client:
        assert (await client.get("/districts/1/users")).status_code == 401
        assert (await client.post("/districts/1/users", json={"ids": []})).status_code == 401
        assert (
            await client.request("DELETE", "/districts/1/users", json={"ids": []})
        ).status_code == 401


async def test_login_dep_not_enforced_when_login_not_required(seed, make_client):
    async def require_auth():
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with await make_client(login_dep=require_auth, login_required=False) as client:
        r = await client.get("/districts/1/users")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Config: child_path_segment override
# ---------------------------------------------------------------------------


async def test_custom_child_path_segment(seed, make_client):
    async with await make_client(child_path_segment="members") as client:
        r = await client.get("/districts/1/members")
        assert r.status_code == 200
