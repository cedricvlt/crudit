"""Child rows, nested routes, m2m links and writes follow the caller's companies.

A user of company A must not reach company B's sale through its children
(``_scope_via``), through a nested route naming B's sale in the URL, through an
m2m link, or by writing B's ids into a body (``company_id``, foreign keys).

Models live on their own ``Base`` so the shared fixtures stay untouched.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import Column, ForeignKey, Integer, String, Table, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from crudit import M2MConfig, crud_router, m2m_router
from crudit.exceptions import CruditConfigError
from crudit.permissions import apply_permissions


class Base(DeclarativeBase):
    pass


user_companies = Table(
    "cs_user_companies",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("cs_users.id"), primary_key=True),
    Column("company_id", Integer, ForeignKey("cs_companies.id"), primary_key=True),
)
sale_tags = Table(
    "cs_sale_tags",
    Base.metadata,
    Column("sale_id", Integer, ForeignKey("cs_sales.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("cs_tags.id"), primary_key=True),
)


class Company(Base):
    __tablename__ = "cs_companies"
    id: Mapped[int] = mapped_column(primary_key=True)


class User(Base):
    __tablename__ = "cs_users"
    id: Mapped[int] = mapped_column(primary_key=True)
    is_superuser: Mapped[bool] = mapped_column(default=False)
    companies: Mapped[list[Company]] = relationship(secondary=user_companies, lazy="selectin")


class Sale(Base):
    __tablename__ = "cs_sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), default="")
    company_id: Mapped[int] = mapped_column(ForeignKey("cs_companies.id"))


class Line(Base):
    """A child with no company of its own: visible iff its sale is."""

    __tablename__ = "cs_lines"
    _scope_via = "sale"
    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(50), default="")
    sale_id: Mapped[int] = mapped_column(ForeignKey("cs_sales.id"))
    sale: Mapped[Sale] = relationship()


class Payment(Base):
    """A grandchild: scoped through its line, then the line's sale."""

    __tablename__ = "cs_payments"
    _scope_via = "line"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("cs_lines.id"))
    line: Mapped[Line] = relationship()


class Note(Base):
    """A nested child without ``_scope_via``: only its route's parent guards it."""

    __tablename__ = "cs_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(50), default="")
    sale_id: Mapped[int] = mapped_column(ForeignKey("cs_sales.id"))
    sale: Mapped[Sale] = relationship()


class Tag(Base):
    __tablename__ = "cs_tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50), default="")
    company_id: Mapped[int] = mapped_column(ForeignKey("cs_companies.id"))


class SaleIn(BaseModel):
    name: str = ""
    company_id: int


class SaleOut(BaseModel):
    id: int
    name: str
    company_id: int


class LineIn(BaseModel):
    label: str = ""


class LinePatch(BaseModel):
    label: str | None = None


class LineOut(BaseModel):
    id: int
    label: str
    sale_id: int


class PaymentOut(BaseModel):
    id: int
    line_id: int


class NoteIn(BaseModel):
    text: str = ""


class NoteOut(BaseModel):
    id: int
    text: str
    sale_id: int


class LineMove(BaseModel):
    """Re-parenting a line: the target sale is a foreign key from the body."""

    sale_id: int | None = None


class TagOut(BaseModel):
    id: int
    name: str


# Company 1 is the caller's; company 2's sale/line/payment/note/tag are not.
OWN, OTHER = 1, 2


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        c1, c2 = Company(id=OWN), Company(id=OTHER)
        session.add_all([c1, c2])
        session.add_all(
            [
                User(id=1, companies=[c1]),
                User(id=9, is_superuser=True, companies=[c1]),
                Sale(id=OWN, company_id=OWN),
                Sale(id=OTHER, company_id=OTHER),
                Line(id=OWN, sale_id=OWN),
                Line(id=OTHER, sale_id=OTHER),
                Payment(id=OWN, line_id=OWN),
                Payment(id=OTHER, line_id=OTHER),
                Note(id=OWN, sale_id=OWN),
                Note(id=OTHER, sale_id=OTHER),
                Tag(id=OWN, company_id=OWN),
                Tag(id=OTHER, company_id=OTHER),
            ]
        )
        await session.commit()
    yield engine
    await engine.dispose()


def _app(engine, user_id: int = 1) -> FastAPI:
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as session:
            yield session

    async def current_user() -> User:
        async with factory() as session:
            return await session.get(User, user_id)

    common = dict(get_db=get_db, login_dep=current_user, mcp_expose=False)
    app = FastAPI()
    app.include_router(
        crud_router(
            Sale,
            list_item_schema=SaleOut,
            read_schema=SaleOut,
            create_schema=SaleIn,
            update_schema=SaleIn,
            **common,
        ),
        prefix="/sales",
    )
    app.include_router(
        crud_router(
            Line,
            list_item_schema=LineOut,
            read_schema=LineOut,
            create_schema=LineIn,
            update_schema=LinePatch,
            path_filters={"sale_id": "sale_id"},
            **common,
        ),
        prefix="/sales/{sale_id}/lines",
    )
    app.include_router(
        crud_router(
            Line,
            list_item_schema=LineOut,
            read_schema=LineOut,
            update_schema=LineMove,
            crud_endpoints=["list", "read", "update"],
            **common,
        ),
        prefix="/lines",
    )
    app.include_router(
        crud_router(
            Payment,
            list_item_schema=PaymentOut,
            read_schema=PaymentOut,
            crud_endpoints=["list", "read", "delete"],
            **common,
        ),
        prefix="/payments",
    )
    app.include_router(
        crud_router(
            Note,
            list_item_schema=NoteOut,
            read_schema=NoteOut,
            create_schema=NoteIn,
            update_schema=NoteIn,
            path_filters={"sale_id": "sale_id"},
            **common,
        ),
        prefix="/sales/{sale_id}/notes",
    )
    app.include_router(
        m2m_router(
            parent_model=Sale,
            child_model=Tag,
            association_table=sale_tags,
            child_schema=TagOut,
            prefix="/sales",
            get_db=get_db,
            login_dep=current_user,
            config=M2MConfig(child_path_segment="tags"),
            mcp_expose=False,
        )
    )
    return app


@pytest_asyncio.fixture
async def client(engine):
    async with AsyncClient(transport=ASGITransport(app=_app(engine)), base_url="http://t") as c:
        yield c


# --- _scope_via ---------------------------------------------------------------


async def test_children_follow_their_parent(client):
    assert [r["id"] for r in (await client.get("/lines")).json()["data"]] == [OWN]
    assert (await client.get(f"/lines/{OWN}")).status_code == 200
    assert (await client.get(f"/lines/{OTHER}")).status_code == 404
    assert (await client.patch(f"/lines/{OTHER}", json={})).status_code == 404


async def test_scope_via_chains_through_grandparents(client):
    assert [r["id"] for r in (await client.get("/payments")).json()["data"]] == [OWN]
    assert (await client.get(f"/payments/{OTHER}")).status_code == 404
    assert (await client.delete(f"/payments/{OTHER}")).status_code == 404
    assert (await client.delete(f"/payments/{OWN}")).status_code == 204


def test_scope_via_must_name_a_many_to_one():
    class Bad(Base):
        __tablename__ = "cs_bad"
        _scope_via = "nope"
        id: Mapped[int] = mapped_column(primary_key=True)

    with pytest.raises(CruditConfigError):
        apply_permissions(select(Bad), Bad, User(id=1, companies=[]), login_required=True)


# --- nested routes --------------------------------------------------------------


async def test_nested_routes_check_the_url_parent(client):
    """Note has no ``_scope_via``: the URL's sale is what guards it."""
    assert (await client.get(f"/sales/{OTHER}/notes")).status_code == 404
    assert (await client.post(f"/sales/{OTHER}/notes", json={})).status_code == 404
    assert (await client.get(f"/sales/{OTHER}/notes/{OTHER}")).status_code == 404
    assert (await client.patch(f"/sales/{OTHER}/notes/{OTHER}", json={})).status_code == 404
    assert (await client.delete(f"/sales/{OTHER}/notes/{OTHER}")).status_code == 404
    assert (await client.get(f"/sales/{OWN}/notes")).status_code == 200


async def test_path_filters_narrow_by_id_lookups(client):
    """``/sales/{own}/notes/{other's note}`` must not reach the other note."""
    assert (await client.get(f"/sales/{OWN}/notes/{OTHER}")).status_code == 404
    assert (await client.patch(f"/sales/{OWN}/notes/{OTHER}", json={})).status_code == 404
    assert (await client.delete(f"/sales/{OWN}/notes/{OTHER}")).status_code == 404
    assert (await client.get(f"/sales/{OWN}/notes/{OWN}")).status_code == 200


# --- m2m ----------------------------------------------------------------------


async def test_m2m_cannot_link_an_invisible_child(client):
    resp = await client.post(f"/sales/{OWN}/tags", json={"ids": [OTHER]})
    assert resp.status_code == 422
    resp = await client.post(f"/sales/{OWN}/tags", json={"ids": [OWN]})
    assert [t["id"] for t in resp.json()] == [OWN]


async def test_m2m_lists_only_visible_children(engine, client):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await session.execute(sale_tags.insert().values(sale_id=OWN, tag_id=OTHER))
        await session.commit()
    assert (await client.get(f"/sales/{OWN}/tags")).json() == []


# --- writes ---------------------------------------------------------------------


async def test_company_id_must_be_one_of_the_users(client):
    resp = await client.post("/sales", json={"company_id": OTHER})
    assert resp.status_code == 422
    assert "company_id" in str(resp.json())
    assert (await client.post("/sales", json={"company_id": OWN})).status_code == 201
    resp = await client.patch(f"/sales/{OWN}", json={"company_id": OTHER})
    assert resp.status_code == 422


async def test_superusers_may_write_into_any_company(engine):
    app = _app(engine, user_id=9)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/sales", json={"company_id": OTHER})).status_code == 201


async def test_foreign_keys_must_point_at_visible_rows(client):
    resp = await client.patch(f"/lines/{OWN}", json={"sale_id": OTHER})
    assert resp.status_code == 422
    assert "sale_id" in str(resp.json())
    assert (await client.patch(f"/lines/{OWN}", json={"sale_id": OWN})).status_code == 200
