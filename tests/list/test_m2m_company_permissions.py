"""Regression tests for company scoping via the user's many-to-many
`companies` relationship.

Reproduces a cross-tenant data leak: a user belonging to one company must only
see that company's rows. The scope is emitted as
``model.company_id IN (<user's company ids>)``; an empty company set must match
no rows. These cases exercise ``apply_permissions`` directly with a realistic
99-vs-1 lead distribution.

Models are defined locally (separate ``Base``/engine) to keep this regression
self-contained, independent of the shared test fixtures.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import Column, ForeignKey, Integer, String, Table, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from crudit.permissions import apply_permissions


class Base(DeclarativeBase):
    pass


user_companies = Table(
    "m2m_user_companies",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("m2m_users.id"), primary_key=True),
    Column("company_id", Integer, ForeignKey("m2m_companies.id"), primary_key=True),
)


class Company(Base):
    __tablename__ = "m2m_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class MultiCompanyUser(Base):
    __tablename__ = "m2m_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))

    # Companies are an eager-loaded M2M relationship (no scalar `company_id`).
    companies: Mapped[list[Company]] = relationship(
        "Company", secondary=user_companies, lazy="selectin"
    )


class Lead(Base):
    __tablename__ = "m2m_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("m2m_companies.id"), nullable=True
    )


@pytest_asyncio.fixture
async def m2m_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        c1 = Company(id=1, name="Company One")
        c8 = Company(id=8, name="Berthier & Associés - Rhône")
        # 99 leads in company 1, 1 lead in company 8 — mirrors the diagnosis.
        leads = [Lead(id=i, name=f"lead-{i}", company_id=1) for i in range(1, 100)]
        leads.append(Lead(id=100, name="lead-100", company_id=8))
        session.add_all([c1, c8, *leads])
        await session.commit()
        yield session

    await engine.dispose()


async def _persist_user(session, user_id: int, company_ids: list[int]) -> MultiCompanyUser:
    """Create a user with the given company links and flush the association rows.

    Assigning ``companies`` (even empty) populates the collection in memory, so
    reading it later in the sync permission code never triggers a lazy load.
    """
    companies = [await session.get(Company, cid) for cid in company_ids]
    user = MultiCompanyUser(id=user_id, name=f"user-{user_id}", companies=companies)
    session.add(user)
    await session.commit()
    return user


@pytest.mark.asyncio
async def test_m2m_user_sees_only_their_company_leads(m2m_session):
    """A user linked only to company 8 must see exactly the one company-8 lead."""
    user = await _persist_user(m2m_session, 1, [8])

    query = apply_permissions(
        select(Lead), Lead, user, login_required=True
    )
    rows = (await m2m_session.execute(query)).scalars().all()

    assert len(rows) == 1
    assert {r.company_id for r in rows} == {8}


@pytest.mark.asyncio
async def test_m2m_user_union_across_companies(m2m_session):
    """A user linked to both companies sees the union of their leads."""
    user = await _persist_user(m2m_session, 2, [1, 8])

    query = apply_permissions(
        select(Lead), Lead, user, login_required=True
    )
    rows = (await m2m_session.execute(query)).scalars().all()

    assert len(rows) == 100
    assert {r.company_id for r in rows} == {1, 8}


@pytest.mark.asyncio
async def test_m2m_user_with_no_companies_sees_nothing(m2m_session):
    """A user with no company links must not see any scoped rows."""
    user = await _persist_user(m2m_session, 3, [])

    query = apply_permissions(
        select(Lead), Lead, user, login_required=True
    )
    rows = (await m2m_session.execute(query)).scalars().all()

    assert rows == []
