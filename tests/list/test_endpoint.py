from __future__ import annotations

import pytest
from crudit import ListConfig


@pytest.mark.asyncio
async def test_basic_list_returns_envelope(seed, make_client):
    async with await make_client(
        ListConfig(
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        body = r.json()
        assert "data" in body
        assert "totalCount" in body
        assert "hasMore" in body
        assert "page" in body
        assert "itemsPerPage" in body


@pytest.mark.asyncio
async def test_path_filter_applied(seed, make_client):
    async with await make_client(
        ListConfig(
            login_required=False,
        )
    ) as client:
        r1 = await client.get("/cities/1/districts")
        r2 = await client.get("/cities/2/districts")
        assert r1.status_code == 200
        assert r2.status_code == 200
        ids1 = {d["id"] for d in r1.json()["data"]}
        ids2 = {d["id"] for d in r2.json()["data"]}
        assert ids1.isdisjoint(ids2)


@pytest.mark.asyncio
async def test_before_query_hook(seed, make_client):
    calls = []

    def before(query, ctx):
        calls.append(1)
        return query

    async with await make_client(
        ListConfig(
            login_required=False,
            before_query=before,
        )
    ) as client:
        await client.get("/cities/1/districts")
        assert calls == [1]


@pytest.mark.asyncio
async def test_after_query_hook(seed, make_client):
    seen = []

    def after(rows, ctx):
        seen.extend(rows)
        return rows

    async with await make_client(
        ListConfig(
            login_required=False,
            after_query=after,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        assert len(seen) == r.json()["totalCount"]


@pytest.mark.asyncio
async def test_async_hooks(seed, make_client):
    log = []

    async def before(query, ctx):
        log.append("before")
        return query

    async def after(rows, ctx):
        log.append("after")
        return rows

    async with await make_client(
        ListConfig(
            login_required=False,
            before_query=before,
            after_query=after,
        )
    ) as client:
        await client.get("/cities/1/districts")
        assert log == ["before", "after"]


@pytest.mark.asyncio
async def test_response_schema_fields(seed, make_client):
    async with await make_client(
        ListConfig(
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        row = r.json()["data"][0]
        assert "id" in row
        assert "name" in row
        assert "is_active" in row
        assert "city_id" in row
        assert "city" in row
