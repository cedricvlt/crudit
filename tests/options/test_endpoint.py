from __future__ import annotations

import pytest

from crudit import CruditConfigError, OptionsConfig, options_endpoint
from tests.conftest import District


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_response_envelope(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        body = r.json()
        assert "data" in body
        assert "total_count" in body
        assert "has_more" in body
        assert "page" not in body
        assert "items_per_page" not in body


@pytest.mark.asyncio
async def test_items_have_id_and_label(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) > 0
        for item in data:
            assert set(item.keys()) == {"id", "label"}
            assert isinstance(item["id"], int)
            assert isinstance(item["label"], str)


@pytest.mark.asyncio
async def test_path_filter_applied(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
        )
    ) as client:
        r1 = await client.get("/cities/1/districts")
        r2 = await client.get("/cities/2/districts")
        ids1 = {d["id"] for d in r1.json()["data"]}
        ids2 = {d["id"] for d in r2.json()["data"]}
        assert ids1.isdisjoint(ids2)


# ---------------------------------------------------------------------------
# label_field vs label_fn
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_label_field(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        data = r.json()["data"]
        labels = {d["label"] for d in data}
        assert "Montmartre" in labels
        assert "Marais" in labels


@pytest.mark.asyncio
async def test_label_fn(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_fn=lambda row: f"{row.city.name} — {row.name}",
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        data = r.json()["data"]
        labels = {d["label"] for d in data}
        assert "Paris — Montmartre" in labels
        assert "Paris — Marais" in labels


@pytest.mark.asyncio
async def test_label_fn_coerced_to_str(seed, make_client):
    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_fn=lambda row: row.id,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        data = r.json()["data"]
        for item in data:
            assert isinstance(item["label"], str)


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def test_no_label_defaults_to_name():
    from fastapi import APIRouter
    config = OptionsConfig(login_required=False)
    router = APIRouter()
    options_endpoint(router=router, path="/districts", model=District, config=config, get_db=lambda: None)
    assert config.label_field == "name"


def test_both_label_raises():
    from fastapi import APIRouter
    router = APIRouter()

    with pytest.raises(CruditConfigError, match="not both"):
        options_endpoint(
            router=router,
            path="/districts",
            model=District,
            config=OptionsConfig(
                login_required=False,
                label_field="name",
                label_fn=lambda row: row.name,
            ),
            get_db=lambda: None,
        )


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_before_query_hook(seed, make_client):
    calls = []

    def before(query, request, user):
        calls.append(1)
        return query

    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
            before_query=before,
        )
    ) as client:
        await client.get("/cities/1/districts")
        assert calls == [1]


@pytest.mark.asyncio
async def test_after_query_hook(seed, make_client):
    seen = []

    def after(rows, request, user):
        seen.extend(rows)
        return rows

    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
            after_query=after,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        assert len(seen) == r.json()["total_count"]


@pytest.mark.asyncio
async def test_async_before_query_hook(seed, make_client):
    calls = []

    async def before(query, request, user):
        calls.append(1)
        return query

    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
            before_query=before,
        )
    ) as client:
        await client.get("/cities/1/districts")
        assert calls == [1]


@pytest.mark.asyncio
async def test_after_query_hook_can_filter(seed, make_client):
    def after(rows, request, user):
        return [r for r in rows if r.is_active]

    async with await make_client(
        OptionsConfig(
            path_filters={"city_id": "city_id"},
            login_required=False,
            label_field="name",
            after_query=after,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        data = r.json()["data"]
        assert all(item["label"] != "Marais" for item in data)
