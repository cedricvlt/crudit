"""Filtering/searching on a string-backed ``TypeDecorator`` column.

Reproduces the failure seen with sqlalchemy_utils' ``PhoneNumberType``: such a
type parses every bound literal (a phone number), so a filter/search string that
isn't a valid phone number raises a parse error when bound. ``FussyPhoneType``
below mimics that behaviour without depending on sqlalchemy_utils.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import String
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from crudit import ListConfig, list_endpoint


class FussyPhoneType(TypeDecorator):
    """String-backed type that rejects any bound value that isn't a '+'-number."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        if not value.startswith("+"):
            raise ValueError(f"'{value}' is not a phone number")
        return value


class Base(DeclarativeBase):
    pass


class Contact(Base):
    __tablename__ = "phone_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(FussyPhoneType, nullable=True)

    _order_fields = ("name",)


class ContactSchema(BaseModel):
    id: int
    name: str
    phone: str | None = None

    model_config = {"from_attributes": True}


@pytest_asyncio.fixture
async def phone_client() -> AsyncGenerator[AsyncClient, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add_all([
            Contact(id=1, name="Alice", phone="+15551230001"),
            Contact(id=2, name="Bob", phone="+15559990002"),
        ])
        await session.commit()

    app = FastAPI()

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as s:
            yield s

    list_endpoint(
        router=app.router,
        path="/contacts",
        model=Contact,
        schema=ContactSchema,
        config=ListConfig(
            filterable_fields=["phone"],
            search_fields=["phone"],
            login_required=False,
        ),
        path_filters=None,
        get_db=get_db,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await engine.dispose()


@pytest.mark.asyncio
async def test_search_on_phone_number_type(phone_client):
    r = await phone_client.get("/contacts?q=5551230")
    assert r.status_code == 200
    data = r.json()["data"]
    assert [c["name"] for c in data] == ["Alice"]


@pytest.mark.asyncio
async def test_ilike_filter_on_phone_number_type(phone_client):
    r = await phone_client.get("/contacts", params={"phone__ilike": "%9990%"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert [c["name"] for c in data] == ["Bob"]


@pytest.mark.asyncio
async def test_eq_filter_on_phone_number_type(phone_client):
    r = await phone_client.get("/contacts", params={"phone": "+15551230001"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert [c["name"] for c in data] == ["Alice"]
