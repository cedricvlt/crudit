from __future__ import annotations

import pytest
from crudit import ListConfig


FILTERABLE = ["name", "is_active", "city.name"]


@pytest.mark.asyncio
async def test_ilike_filter(seed, make_client):
    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            filterable_fields=FILTERABLE,
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?name__ilike=%25arais%25")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "Marais"


@pytest.mark.asyncio
async def test_eq_filter_bool(seed, make_client):
    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            filterable_fields=FILTERABLE,
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?is_active=false")
        assert r.status_code == 200
        data = r.json()["data"]
        assert all(not d["is_active"] for d in data)


@pytest.mark.asyncio
async def test_nested_filter(seed, make_client):
    # All districts regardless of city, filtered by city.name
    async with await make_client(
        ListConfig(
            path_filters={},
            filterable_fields=["city.name", "name", "is_active"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?city.name__ilike=Paris")
        assert r.status_code == 200
        data = r.json()["data"]
        assert all(d["city_id"] == 1 for d in data)


@pytest.mark.asyncio
async def test_unknown_filter_returns_400(seed, make_client):
    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            filterable_fields=["name"],
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?secret_field=x")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_custom_filter_fn(seed, make_client):
    from sqlalchemy.sql import Select

    def active_only(query: Select, value: str, current_user) -> Select:
        from tests.conftest import District
        return query.where(District.is_active == True)  # noqa: E712

    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            filterable_fields=["active_only"],
            filter_fns={"active_only": active_only},
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?active_only=1")
        assert r.status_code == 200
        data = r.json()["data"]
        assert all(d["is_active"] for d in data)


@pytest.mark.asyncio
async def test_default_filters(seed, make_client):
    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            default_filters={"is_active": True},
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        data = r.json()["data"]
        assert all(d["is_active"] for d in data)
