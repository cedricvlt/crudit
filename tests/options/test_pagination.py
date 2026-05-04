from __future__ import annotations

import pytest

from crudit import OptionsConfig


@pytest.mark.asyncio
async def test_offset_limit_pagination(seed, make_client):
    async with await make_client(
        OptionsConfig(
            login_required=False,
            label_field="name",
            sortable_fields=["name"],
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=name&offset=0&limit=1")
        assert r.status_code == 200
        body = r.json()
        assert len(body["data"]) == 1
        assert body["hasMore"] is True
        assert body["totalCount"] == 2


@pytest.mark.asyncio
async def test_second_page_via_offset(seed, make_client):
    async with await make_client(
        OptionsConfig(
            login_required=False,
            label_field="name",
            sortable_fields=["name"],
        )
    ) as client:
        r1 = await client.get("/cities/1/districts?sort=name&offset=0&limit=1")
        r2 = await client.get("/cities/1/districts?sort=name&offset=1&limit=1")
        id1 = r1.json()["data"][0]["id"]
        id2 = r2.json()["data"][0]["id"]
        assert id1 != id2


@pytest.mark.asyncio
async def test_no_more_when_exhausted(seed, make_client):
    async with await make_client(
        OptionsConfig(
            login_required=False,
            label_field="name",
        )
    ) as client:
        r = await client.get("/cities/1/districts?limit=100")
        assert r.json()["hasMore"] is False
