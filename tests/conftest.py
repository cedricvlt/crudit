from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest_asyncio
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


district_allowed_users = Table(
    "district_allowed_users",
    Base.metadata,
    Column("district_id", Integer, ForeignKey("districts.id"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))

    _order_fields = ("name",)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)

    company: Mapped[Company | None] = relationship("Company")

    _order_fields = ("name",)


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))

    districts: Mapped[list["District"]] = relationship("District", back_populates="city")

    _order_fields = ("name",)


class District(Base):
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    sort_order: Mapped[int | None] = mapped_column(nullable=True, default=None)

    city: Mapped[City] = relationship("City", back_populates="districts")
    allowed_users: Mapped[list[User]] = relationship(
        "User", secondary=district_allowed_users
    )

    _order_fields = ("name",)


# ---------------------------------------------------------------------------
# Engine and session
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="session")
async def engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def seed(db_session: AsyncSession):
    company1 = Company(id=1, name="Acme Corp")
    company2 = Company(id=2, name="Other Corp")

    user1 = User(id=1, name="Alice", company_id=1)
    user2 = User(id=2, name="Bob", company_id=2)
    user3 = User(id=3, name="Carol", company_id=1)

    city1 = City(id=1, name="Paris")
    city2 = City(id=2, name="London")

    d1 = District(id=1, name="Montmartre", city_id=1, company_id=1, is_active=True,
                  created_at=datetime(2024, 1, 15, tzinfo=timezone.utc))
    d2 = District(id=2, name="Marais", city_id=1, company_id=1, is_active=False,
                  created_at=datetime(2024, 6, 1, tzinfo=timezone.utc))
    d3 = District(id=3, name="Downtown", city_id=2, company_id=2, is_active=True)
    d4 = District(id=4, name="Uptown", city_id=2, company_id=2, is_active=True)

    # district 1 allows user3 explicitly (different company)
    d1.allowed_users.append(user3)

    db_session.add_all([company1, company2, user1, user2, user3, city1, city2, d1, d2, d3, d4])
    await db_session.commit()

    yield {"companies": [company1, company2], "users": [user1, user2, user3],
           "cities": [city1, city2], "districts": [d1, d2, d3, d4]}

    # Cleanup
    for obj in [d1, d2, d3, d4, city1, city2, user1, user2, user3, company1, company2]:
        await db_session.delete(obj)
    await db_session.commit()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CitySchema(BaseModel):
    id: int
    name: str


class DistrictSchema(BaseModel):
    id: int
    name: str
    is_active: bool
    city_id: int
    city: CitySchema
    created_at: datetime | None = None
    created_by: int | None = None
    updated_at: datetime | None = None
    updated_by: int | None = None


class DistrictCreateSchema(BaseModel):
    name: str
    is_active: bool = True


class DistrictCreateFlatSchema(BaseModel):
    """For tests that create a district without a city path param."""
    name: str
    is_active: bool = True
    city_id: int


class DistrictUpdateSchema(BaseModel):
    name: str | None = None
    is_active: bool | None = None
