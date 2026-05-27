from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from crudit import CruditConfigError, OptionsConfig, options_endpoint
from tests.conftest import Base, CitySchema, District


class DistrictOptionSchema(BaseModel):
    """Full output schema for the options endpoint, including a nested m2o.

    `label` is read from the model's `name` attribute via validation_alias.
    """
    id: int
    label: str = Field(validation_alias="name")
    is_active: bool
    city: CitySchema


class DistrictComputedLabelSchema(BaseModel):
    """Builds the label with a @computed_field from a nested relationship.

    `name` and `city` feed the label but are excluded from the output, so the
    serialised shape stays {id, label}.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: int
    name: str = Field(exclude=True)
    city: CitySchema = Field(exclude=True)

    @computed_field
    @property
    def label(self) -> str:
        return f"{self.city.name} — {self.name}"


class DistrictIdLabelSchema(BaseModel):
    """Computes the label from a non-str field to exercise str coercion."""

    id: int

    @computed_field
    @property
    def label(self) -> str:
        return str(self.id)


# ---------------------------------------------------------------------------
# Response shape (default schema: {id, label} from `name`)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_response_envelope(seed, make_client):
    async with await make_client(
        OptionsConfig(login_required=False)
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        body = r.json()
        assert "data" in body
        assert "totalCount" in body
        assert "hasMore" in body
        assert "page" not in body
        assert "itemsPerPage" not in body


@pytest.mark.asyncio
async def test_items_have_id_and_label(seed, make_client):
    async with await make_client(
        OptionsConfig(login_required=False)
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
        OptionsConfig(login_required=False)
    ) as client:
        r1 = await client.get("/cities/1/districts")
        r2 = await client.get("/cities/2/districts")
        ids1 = {d["id"] for d in r1.json()["data"]}
        ids2 = {d["id"] for d in r2.json()["data"]}
        assert ids1.isdisjoint(ids2)


# ---------------------------------------------------------------------------
# Label sources
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_default_label_from_name(seed, make_client):
    """With no schema, the label defaults to the model's `name` column."""
    async with await make_client(
        OptionsConfig(login_required=False)
    ) as client:
        r = await client.get("/cities/1/districts")
        labels = {d["label"] for d in r.json()["data"]}
        assert "Montmartre" in labels
        assert "Marais" in labels


@pytest.mark.asyncio
async def test_computed_label_from_relationship(seed, make_client):
    """A @computed_field schema can build the label from a nested relationship;
    declaring `city` drives the join automatically."""
    async with await make_client(
        OptionsConfig(login_required=False),
        schema=DistrictComputedLabelSchema,
    ) as client:
        r = await client.get("/cities/1/districts")
        data = r.json()["data"]
        labels = {d["label"] for d in data}
        assert "Paris — Montmartre" in labels
        assert "Paris — Marais" in labels
        # name/city are excluded, so the shape stays {id, label}
        assert set(data[0].keys()) == {"id", "label"}


@pytest.mark.asyncio
async def test_computed_label_coerced_to_str(seed, make_client):
    async with await make_client(
        OptionsConfig(login_required=False),
        schema=DistrictIdLabelSchema,
    ) as client:
        r = await client.get("/cities/1/districts")
        for item in r.json()["data"]:
            assert isinstance(item["label"], str)


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------

def test_no_schema_no_name_column_raises():
    """Without a schema, a model lacking a `name` column cannot default the label."""
    from fastapi import APIRouter

    class Widget(Base):
        __tablename__ = "widgets_no_name"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)

    router = APIRouter()
    with pytest.raises(CruditConfigError, match="no `name` column"):
        options_endpoint(
            router=router,
            path="/widgets",
            model=Widget,
            config=OptionsConfig(login_required=False),
            get_db=lambda: None,
        )


def test_default_schema_registers():
    """A model with a `name` column registers fine without an explicit schema."""
    from fastapi import APIRouter

    router = APIRouter()
    options_endpoint(
        router=router,
        path="/districts",
        model=District,
        config=OptionsConfig(login_required=False),
        get_db=lambda: None,
    )


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_before_query_hook(seed, make_client):
    calls = []

    def before(query, ctx):
        calls.append(1)
        return query

    async with await make_client(
        OptionsConfig(
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
        OptionsConfig(
            login_required=False,
            after_query=after,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        assert len(seen) == r.json()["totalCount"]


@pytest.mark.asyncio
async def test_async_before_query_hook(seed, make_client):
    calls = []

    async def before(query, ctx):
        calls.append(1)
        return query

    async with await make_client(
        OptionsConfig(
            login_required=False,
            before_query=before,
        )
    ) as client:
        await client.get("/cities/1/districts")
        assert calls == [1]


@pytest.mark.asyncio
async def test_after_query_hook_can_filter(seed, make_client):
    def after(rows, ctx):
        return [r for r in rows if r.is_active]

    async with await make_client(
        OptionsConfig(
            login_required=False,
            after_query=after,
        )
    ) as client:
        r = await client.get("/cities/1/districts")
        data = r.json()["data"]
        assert all(item["label"] != "Marais" for item in data)


# ---------------------------------------------------------------------------
# Custom (full) schema
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_schema_serialises_full_rows(seed, make_client):
    """A custom schema serialises full rows, not just {id, label}."""
    async with await make_client(
        OptionsConfig(login_required=False),
        schema=DistrictOptionSchema,
    ) as client:
        r = await client.get("/cities/1/districts")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) > 0
        for item in data:
            assert set(item.keys()) == {"id", "label", "is_active", "city"}
            # nested m2o relationship was eager-loaded and serialised
            assert item["city"]["name"] == "Paris"
        labels = {item["label"] for item in data}
        assert "Montmartre" in labels
