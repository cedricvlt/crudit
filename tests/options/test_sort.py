from __future__ import annotations

import pytest

from crudit import OptionsConfig


@pytest.mark.asyncio
async def test_sort_ascending(seed, make_client):
    async with await make_client(
        OptionsConfig(
            login_required=False,
            label_field="name",
            sortable_fields=["name"],
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=name")
        assert r.status_code == 200
        labels = [d["label"] for d in r.json()["data"]]
        assert labels == sorted(labels)


@pytest.mark.asyncio
async def test_sort_descending(seed, make_client):
    async with await make_client(
        OptionsConfig(
            login_required=False,
            label_field="name",
            sortable_fields=["name"],
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=-name")
        assert r.status_code == 200
        labels = [d["label"] for d in r.json()["data"]]
        assert labels == sorted(labels, reverse=True)


@pytest.mark.asyncio
async def test_sort_nested_field(seed, make_client):
    async with await make_client(
        OptionsConfig(
            login_required=False,
            label_field="name",
            sortable_fields=["city.name", "name"],
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=city.name,name")
        assert r.status_code == 200
        assert r.json()["totalCount"] == 2


@pytest.mark.asyncio
async def test_unknown_sort_field_returns_400(seed, make_client):
    async with await make_client(
        OptionsConfig(
            login_required=False,
            label_field="name",
            sortable_fields=["name"],
        )
    ) as client:
        r = await client.get("/cities/1/districts?sort=is_active")
        assert r.status_code == 400
