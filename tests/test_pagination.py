from __future__ import annotations

import pytest
from crudite import ListConfig
from crudite.list.pagination import resolve_pagination


def test_page_mode_defaults():
    p = resolve_pagination(None, None, None, None)
    assert p.page == 1
    assert p.items_per_page == 25
    assert p.sql_offset == 0
    assert p.sql_limit == 25


def test_page_mode_explicit():
    p = resolve_pagination(3, 10, None, None)
    assert p.page == 3
    assert p.items_per_page == 10
    assert p.sql_offset == 20
    assert p.sql_limit == 10


def test_offset_mode():
    p = resolve_pagination(None, None, 50, 20)
    assert p.sql_offset == 50
    assert p.sql_limit == 20
    assert p.page == 3       # 50 // 20 + 1
    assert p.items_per_page == 20


def test_offset_mode_zero():
    p = resolve_pagination(None, None, 0, 10)
    assert p.page == 1
    assert p.sql_offset == 0


def test_offset_mode_takes_priority_when_mixed():
    # offset present → offset mode, page param ignored
    p = resolve_pagination(2, 10, 0, 5)
    assert p.sql_limit == 5
    assert p.sql_offset == 0


@pytest.mark.asyncio
async def test_has_more_true(seed, make_client):
    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?page=1&items_per_page=1")
        assert r.status_code == 200
        body = r.json()
        assert body["has_more"] is True
        assert body["total_count"] == 2


@pytest.mark.asyncio
async def test_has_more_false(seed, make_client):
    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?items_per_page=100")
        assert r.status_code == 200
        body = r.json()
        assert body["has_more"] is False


@pytest.mark.asyncio
async def test_count_only(seed, make_client):
    async with await make_client(
        ListConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
        )
    ) as client:
        r = await client.get("/cities/1/districts?count_only=true")
        assert r.status_code == 200
        body = r.json()
        assert body == {"total_count": 2}
        assert "data" not in body
