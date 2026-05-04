from __future__ import annotations

import pytest
from crudit import ListConfig


SORTABLE = ["name", "is_active", "city.name"]


@pytest.mark.asyncio
async def test_default_sort(seed, make_client):
    async with await make_client(
        ListConfig(
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        names = [d["name"] for d in r.json()["data"]]
        assert names == sorted(names)


@pytest.mark.asyncio
async def test_sort_asc(seed, make_client):
    async with await make_client(
        ListConfig(
            sortable_fields=SORTABLE,
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=name")
        assert r.status_code == 200
        names = [d["name"] for d in r.json()["data"]]
        assert names == sorted(names)


@pytest.mark.asyncio
async def test_sort_desc(seed, make_client):
    async with await make_client(
        ListConfig(
            sortable_fields=SORTABLE,
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=-name")
        assert r.status_code == 200
        names = [d["name"] for d in r.json()["data"]]
        assert names == sorted(names, reverse=True)


@pytest.mark.asyncio
async def test_sort_nested(seed, make_client):
    async with await make_client(
        ListConfig(
            sortable_fields=["city.name", "name"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=city.name,-name")
        assert r.status_code == 200
        assert r.json()["totalCount"] > 0


@pytest.mark.asyncio
async def test_unknown_sort_returns_400(seed, make_client):
    async with await make_client(
        ListConfig(
            sortable_fields=["name"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=secret")
        assert r.status_code == 400
