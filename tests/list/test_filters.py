from __future__ import annotations

from datetime import date
from unittest.mock import patch

import crudit.list.filters as filters_module
import pytest
from crudit import ListConfig


def _mock_date(fixed: date):
    class _D(date):
        @classmethod
        def today(cls):
            return fixed
    return _D


FILTERABLE = ["name", "is_active", "created_at", "city.name"]


@pytest.mark.asyncio
async def test_ilike_filter(seed, make_client):
    async with await make_client(
        ListConfig(
            filterable_fields=FILTERABLE,
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?name__ilike=%arais%")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "Marais"


@pytest.mark.asyncio
async def test_eq_filter_bool(seed, make_client):
    async with await make_client(
        ListConfig(
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
async def test_date_gte_filter(seed, make_client):
    async with await make_client(
        ListConfig(
            filterable_fields=FILTERABLE,
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?created_at__gte=2024-03-01")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "Marais"


@pytest.mark.asyncio
async def test_date_lte_filter(seed, make_client):
    async with await make_client(
        ListConfig(
            filterable_fields=FILTERABLE,
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?created_at__lte=2024-03-01")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["name"] == "Montmartre"


@pytest.mark.asyncio
async def test_date_lte_includes_boundary_day(seed, make_client):
    # created_at__lte=2024-01-15 must include Montmartre which has created_at=2024-01-15 00:00:00 UTC
    async with await make_client(
        ListConfig(
            filterable_fields=FILTERABLE,
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?created_at__lte=2024-01-15")
        assert r.status_code == 200
        names = {d["name"] for d in r.json()["data"]}
        assert "Montmartre" in names


@pytest.mark.asyncio
async def test_multi_value_filter_as_or(seed, make_client):
    async with await make_client(
        ListConfig(
            filterable_fields=["company_id"],
            login_required=False,
        ),
        path_filters=None,
    ) as client:
        r = await client.get("/cities/1/districts?company_id=1&company_id=2")
        assert r.status_code == 200
        data = r.json()["data"]
        ids = {d["city_id"] for d in data}
        assert ids == {1, 2}
        assert len(data) == 4  # all districts from both companies


@pytest.mark.asyncio
async def test_default_filters(seed, make_client):
    async with await make_client(
        ListConfig(
            default_filters={"is_active": True},
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        data = r.json()["data"]
        assert all(d["is_active"] for d in data)


# ---------------------------------------------------------------------------
# Date period filters
# Seed: Montmartre=2024-01-15, Marais=2024-06-01
# ---------------------------------------------------------------------------

_DATE_CONFIG = ListConfig(
    filterable_fields=FILTERABLE,
    login_required=False,
)


@pytest.mark.asyncio
async def test_year_filter(seed, make_client):
    async with await make_client(_DATE_CONFIG) as client:
        r = await client.get("/cities/1/districts?created_at__year=2024")
        assert r.status_code == 200
        names = {d["name"] for d in r.json()["data"]}
        assert names == {"Montmartre", "Marais"}


@pytest.mark.asyncio
async def test_quarter_filter_q1(seed, make_client):
    async with await make_client(_DATE_CONFIG) as client:
        r = await client.get("/cities/1/districts?created_at__quarter=2024-Q1")
        assert r.status_code == 200
        names = {d["name"] for d in r.json()["data"]}
        assert names == {"Montmartre"}


@pytest.mark.asyncio
async def test_quarter_filter_q2(seed, make_client):
    async with await make_client(_DATE_CONFIG) as client:
        r = await client.get("/cities/1/districts?created_at__quarter=2024-Q2")
        assert r.status_code == 200
        names = {d["name"] for d in r.json()["data"]}
        assert names == {"Marais"}


@pytest.mark.asyncio
async def test_month_filter(seed, make_client):
    async with await make_client(_DATE_CONFIG) as client:
        r = await client.get("/cities/1/districts?created_at__month=2024-01")
        assert r.status_code == 200
        names = {d["name"] for d in r.json()["data"]}
        assert names == {"Montmartre"}


@pytest.mark.asyncio
async def test_week_filter(seed, make_client):
    # Jan 15 2024 is ISO week W03
    async with await make_client(_DATE_CONFIG) as client:
        r = await client.get("/cities/1/districts?created_at__week=2024-W03")
        assert r.status_code == 200
        names = {d["name"] for d in r.json()["data"]}
        assert names == {"Montmartre"}


@pytest.mark.asyncio
async def test_relative_yesterday(seed, make_client):
    # today=2024-01-16 → yesterday=2024-01-15 → Montmartre
    async with await make_client(_DATE_CONFIG) as client:
        with patch.object(filters_module, "date", _mock_date(date(2024, 1, 16))):
            r = await client.get("/cities/1/districts?created_at__relative=yesterday")
        assert r.status_code == 200
        names = {d["name"] for d in r.json()["data"]}
        assert names == {"Montmartre"}


@pytest.mark.asyncio
async def test_relative_this_year(seed, make_client):
    # today=2024-06-15 → this-year=[2024-01-01, 2025-01-01) → both
    async with await make_client(_DATE_CONFIG) as client:
        with patch.object(filters_module, "date", _mock_date(date(2024, 6, 15))):
            r = await client.get("/cities/1/districts?created_at__relative=this-year")
        assert r.status_code == 200
        names = {d["name"] for d in r.json()["data"]}
        assert names == {"Montmartre", "Marais"}


@pytest.mark.asyncio
async def test_invalid_year(seed, make_client):
    async with await make_client(_DATE_CONFIG) as client:
        r = await client.get("/cities/1/districts?created_at__year=notayear")
        assert r.status_code in (400, 422)  # FastAPI validates int type before handler


@pytest.mark.asyncio
async def test_invalid_quarter(seed, make_client):
    async with await make_client(_DATE_CONFIG) as client:
        r = await client.get("/cities/1/districts?created_at__quarter=2024-Q5")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_invalid_month(seed, make_client):
    async with await make_client(_DATE_CONFIG) as client:
        r = await client.get("/cities/1/districts?created_at__month=2024-13")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_invalid_week(seed, make_client):
    async with await make_client(_DATE_CONFIG) as client:
        r = await client.get("/cities/1/districts?created_at__week=bad")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_invalid_relative(seed, make_client):
    async with await make_client(_DATE_CONFIG) as client:
        r = await client.get("/cities/1/districts?created_at__relative=someday")
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Collection (o2m / m2m) relationship filters via EXISTS subqueries.
# Seed: city 1 holds Montmartre (d1) and Marais (d2); d1.allowed_users == [user3]
# (Carol, city "Paris"). DistrictSchema does NOT declare allowed_users,
# proving a collection can be filtered without being embedded in the response.
# ---------------------------------------------------------------------------

_M2M_CONFIG = ListConfig(
    filterable_fields=[
        "name",
        "allowed_users.id",
        "allowed_users.name",
        "allowed_users.city.name",
    ],
    login_required=False,
)


@pytest.mark.asyncio
async def test_m2m_filter_in(seed, make_client):
    # The user's case: districts having an allowed_user whose id is in {3}.
    async with await make_client(_M2M_CONFIG) as client:
        r = await client.get("/cities/1/districts?allowed_users.id__in=3")
        assert r.status_code == 200
        data = r.json()["data"]
        assert [d["name"] for d in data] == ["Montmartre"]


@pytest.mark.asyncio
async def test_m2m_filter_eq(seed, make_client):
    async with await make_client(_M2M_CONFIG) as client:
        r = await client.get("/cities/1/districts?allowed_users.id=3")
        assert r.status_code == 200
        data = r.json()["data"]
        assert [d["name"] for d in data] == ["Montmartre"]


@pytest.mark.asyncio
async def test_m2m_filter_no_match(seed, make_client):
    async with await make_client(_M2M_CONFIG) as client:
        r = await client.get("/cities/1/districts?allowed_users.id__in=999")
        assert r.status_code == 200
        assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_m2m_filter_nested_attr_ilike(seed, make_client):
    async with await make_client(_M2M_CONFIG) as client:
        r = await client.get("/cities/1/districts?allowed_users.name__ilike=Carol")
        assert r.status_code == 200
        data = r.json()["data"]
        assert [d["name"] for d in data] == ["Montmartre"]


@pytest.mark.asyncio
async def test_m2m_filter_collection_then_m2o(seed, make_client):
    # allowed_users (m2m) -> city (m2o): any(... has(...)) nesting.
    # district 1 (Montmartre) has Carol (user3), whose city is Paris.
    async with await make_client(_M2M_CONFIG) as client:
        r = await client.get("/cities/1/districts?allowed_users.city.name__ilike=Par%")
        assert r.status_code == 200
        data = r.json()["data"]
        assert [d["name"] for d in data] == ["Montmartre"]


@pytest.mark.asyncio
async def test_m2m_filter_no_row_duplication(seed, make_client):
    # An EXISTS subquery must not multiply rows even when several allowed_users
    # would match: id__in covering the match returns Montmartre exactly once.
    async with await make_client(_M2M_CONFIG) as client:
        r = await client.get("/cities/1/districts?allowed_users.id__in=1,2,3")
        assert r.status_code == 200
        body = r.json()
        assert [d["name"] for d in body["data"]] == ["Montmartre"]
        assert body["totalCount"] == 1


# ---------------------------------------------------------------------------
# Range operators (lt/lte/gt/gte) are rejected on id (PK/FK) columns.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_range_operator_rejected_on_pk_id(seed, make_client):
    async with await make_client(
        ListConfig(filterable_fields=["id"], login_required=False)
    ) as client:
        r = await client.get("/cities/1/districts?id__gte=1")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_range_operator_rejected_on_fk_id(seed, make_client):
    async with await make_client(
        ListConfig(filterable_fields=["company_id"], login_required=False),
        path_filters=None,
    ) as client:
        r = await client.get("/cities/1/districts?company_id__lt=5")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_range_operator_rejected_on_m2m_id(seed, make_client):
    async with await make_client(_M2M_CONFIG) as client:
        r = await client.get("/cities/1/districts?allowed_users.id__gt=1")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_eq_and_in_still_allowed_on_pk_id(seed, make_client):
    # Only range ops are blocked on id columns; equality/in remain valid.
    async with await make_client(
        ListConfig(filterable_fields=["id"], login_required=False)
    ) as client:
        r = await client.get("/cities/1/districts?id__in=1,2,3")
        assert r.status_code == 200
