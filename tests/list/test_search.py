from __future__ import annotations

import pytest
from crudit import ListConfig


@pytest.mark.asyncio
async def test_search_by_name(seed, make_client):
    async with await make_client(
        ListConfig(
            search_fields=["name"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?q=mont")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "Montmartre"


@pytest.mark.asyncio
async def test_search_no_match(seed, make_client):
    async with await make_client(
        ListConfig(
            search_fields=["name"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?q=zzznomatch")
        assert r.status_code == 200
        assert r.json()["totalCount"] == 0


@pytest.mark.asyncio
async def test_search_nested_field(seed, make_client):
    async with await make_client(
        ListConfig(
            search_fields=["city.name"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?q=Par")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 2
        assert all(d["city"]["name"] == "Paris" for d in data)


# ---------------------------------------------------------------------------
# Search across a collection (m2m) relationship via EXISTS subqueries.
# Seed: city 1 holds Montmartre (d1) and Marais (d2); d1.allowed_users == [user3]
# (Carol). DistrictSchema does NOT declare allowed_users, proving a collection
# can be searched without being embedded in the response.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_m2m_nested_field(seed, make_client):
    # Match a district by the name of one of its allowed_users (m2m).
    async with await make_client(
        ListConfig(
            search_fields=["allowed_users.name"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?q=Carol")
        assert r.status_code == 200
        data = r.json()["data"]
        assert [d["name"] for d in data] == ["Montmartre"]


@pytest.mark.asyncio
async def test_search_m2m_no_match(seed, make_client):
    async with await make_client(
        ListConfig(
            search_fields=["allowed_users.name"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?q=zzznomatch")
        assert r.status_code == 200
        assert r.json()["totalCount"] == 0


@pytest.mark.asyncio
async def test_search_m2m_no_row_duplication(seed, db_session, make_client):
    # An EXISTS subquery must not multiply rows even when several allowed_users
    # match the query. Add a second matching user to d1, then a query matching
    # both ("l" is in both "Carol" and "Alice") returns Montmartre exactly once.
    from tests.conftest import District, User

    district = await db_session.get(District, 1)
    user1 = await db_session.get(User, 1)  # Alice
    district.allowed_users.append(user1)
    await db_session.commit()

    async with await make_client(
        ListConfig(
            search_fields=["allowed_users.name"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?q=l")
        assert r.status_code == 200
        body = r.json()
        assert [d["name"] for d in body["data"]] == ["Montmartre"]
        assert body["totalCount"] == 1


@pytest.mark.asyncio
async def test_search_m2m_or_with_plain_field(seed, make_client):
    # OR semantics across a plain column and an m2m path: a match on either side
    # counts. "Carol" matches via allowed_users; "Marais" matches via name.
    async with await make_client(
        ListConfig(
            search_fields=["name", "allowed_users.name"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?q=Carol")
        assert r.status_code == 200
        assert [d["name"] for d in r.json()["data"]] == ["Montmartre"]

        r = await client.get("/cities/1/districts?q=Marais")
        assert r.status_code == 200
        assert [d["name"] for d in r.json()["data"]] == ["Marais"]


@pytest.mark.asyncio
async def test_custom_search_fn(seed, make_client):
    from sqlalchemy.sql import Select

    def custom_search(query: Select, q: str, current_user) -> Select:
        from tests.conftest import District
        return query.where(District.name == q)

    async with await make_client(
        ListConfig(
            search_fn=custom_search,
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?q=Marais")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "Marais"
