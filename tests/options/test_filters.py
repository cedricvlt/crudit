from __future__ import annotations

import pytest

from crudit import OptionsConfig


@pytest.mark.asyncio
async def test_filter_by_plain_field(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
            filterable_fields=["is_active"],
        )
    ) as client:
        r = await client.get("/cities/1/districts?is_active=true")
        assert r.status_code == 200
        data = r.json()["data"]
        assert all(item["label"] != "Marais" for item in data)
        assert any(item["label"] == "Montmartre" for item in data)


@pytest.mark.asyncio
async def test_filter_by_nested_field(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
            filterable_fields=["city.name"],
        )
    ) as client:
        r = await client.get("/cities/1/districts?city.name=Paris")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 2


@pytest.mark.asyncio
async def test_unknown_filter_returns_400(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
            filterable_fields=["name"],
        )
    ) as client:
        r = await client.get("/cities/1/districts?is_active=true")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_custom_filter_fn(seed, make_client):
    def active_filter(query, value, user):
        from tests.conftest import District
        active = value.lower() in ("true", "1")
        return query.where(District.is_active == active)

    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
            filterable_fields=["is_active"],
            filter_fns={"is_active": active_filter},
        )
    ) as client:
        r = await client.get("/cities/1/districts?is_active=false")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["label"] == "Marais"


@pytest.mark.asyncio
async def test_multi_value_filter_as_or(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={},
            login_required=False,
            label_field="name",
            filterable_fields=["city_id"],
        )
    ) as client:
        r = await client.get("/cities/1/districts?city_id=1&city_id=2")
        assert r.status_code == 200
        data = r.json()["data"]
        labels = {item["label"] for item in data}
        assert labels == {"Montmartre", "Marais", "Downtown", "Uptown"}


@pytest.mark.asyncio
async def test_default_filters(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
            default_filters={"is_active": True},
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["label"] == "Montmartre"


@pytest.mark.asyncio
async def test_year_filter(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={},
            login_required=False,
            label_field="name",
            filterable_fields=["created_at"],
        )
    ) as client:
        r = await client.get("/cities/1/districts?created_at__year=2024")
        assert r.status_code == 200
        labels = {item["label"] for item in r.json()["data"]}
        assert labels == {"Montmartre", "Marais"}
