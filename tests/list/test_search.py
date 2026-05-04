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
