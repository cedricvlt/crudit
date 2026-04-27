from __future__ import annotations

import pytest

from crudit import OptionsConfig


@pytest.mark.asyncio
async def test_search_by_field(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
            search_fields=["name"],
        )
    ) as client:
        r = await client.get("/cities/1/districts?q=arais")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["label"] == "Marais"


@pytest.mark.asyncio
async def test_search_no_match(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
            search_fields=["name"],
        )
    ) as client:
        r = await client.get("/cities/1/districts?q=xyz")
        assert r.status_code == 200
        assert r.json()["totalCount"] == 0


@pytest.mark.asyncio
async def test_custom_search_fn(seed, make_client):
    def my_search(query, q, user):
        from tests.conftest import District
        return query.where(District.name.ilike(f"{q}%"))

    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
            search_fn=my_search,
        )
    ) as client:
        r = await client.get("/cities/1/districts?q=Mont")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["label"] == "Montmartre"
