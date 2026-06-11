from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest_asyncio
from pydantic import BaseModel
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Table, UniqueConstraint
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


user_companies = Table(
    "user_companies",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("company_id", Integer, ForeignKey("companies.id"), primary_key=True),
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
    city_id: Mapped[int | None] = mapped_column(ForeignKey("cities.id"), nullable=True)

    # Users are multi-company: company membership is a M2M relationship, eager
    # loaded so crudit can read it inside the async request handler.
    companies: Mapped[list[Company]] = relationship(
        "Company", secondary=user_companies, lazy="selectin"
    )
    # A plain many-to-one, used by tests that exercise m2m -> m2o traversal.
    city: Mapped[City | None] = relationship("City")

    _order_fields = ("name",)


class Country(Base):
    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))

    cities: Mapped[list["City"]] = relationship(
        "City", back_populates="country"
    )

    _order_fields = ("name",)


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    country_id: Mapped[int | None] = mapped_column(ForeignKey("countries.id"), nullable=True)

    country: Mapped[Country | None] = relationship("Country", back_populates="cities")
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
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    sort_order: Mapped[int | None] = mapped_column(nullable=True, default=None)

    city: Mapped[City] = relationship("City", back_populates="districts")
    created_by: Mapped[User | None] = relationship("User", foreign_keys=[created_by_id])
    updated_by: Mapped[User | None] = relationship("User", foreign_keys=[updated_by_id])
    allowed_users: Mapped[list[User]] = relationship(
        "User", secondary=district_allowed_users
    )

    _order_fields = ("name",)

    @property
    def display_name(self) -> str:
        return f"{self.name} #{self.id}"

    @property
    def summary(self) -> "DistrictSummary":
        return DistrictSummary(label=self.name, active=self.is_active)


class DistrictSummary:
    """Plain Python object returned by `District.summary`.

    Used by tests to exercise schemas where a Pydantic field maps to a
    @property returning a BaseModel-shaped object (read via Pydantic's
    `from_attributes=True`).
    """

    def __init__(self, label: str, active: bool) -> None:
        self.label = label
        self.active = active


class Tag(Base):
    """Test model exercising all three unique-constraint styles:
    - column-level unique=True on `slug`
    - composite UniqueConstraint on (city_id, name)
    - unique Index on `code` (nullable, to test NULL semantics)
    """

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("city_id", "name", name="uq_tag_city_name"),
        Index("ix_tag_code_unique", "code", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))

    _order_fields = ("name",)


# ---------------------------------------------------------------------------
# Registry isolation
# ---------------------------------------------------------------------------

import pytest

from crudit import registry as crudit_registry


@pytest.fixture(autouse=True)
def _reset_crudit_registry():
    crudit_registry.reset()
    yield
    crudit_registry.reset()


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

    user1 = User(id=1, name="Alice", companies=[company1], city_id=1)
    user2 = User(id=2, name="Bob", companies=[company2], city_id=2)
    user3 = User(id=3, name="Carol", companies=[company1], city_id=1)

    country1 = Country(id=1, name="France")
    country2 = Country(id=2, name="UK")

    city1 = City(id=1, name="Paris", country_id=1)
    city2 = City(id=2, name="London", country_id=2)

    d1 = District(id=1, name="Montmartre", city_id=1, company_id=1, is_active=True,
                  created_at=datetime(2024, 1, 15, tzinfo=timezone.utc))
    d2 = District(id=2, name="Marais", city_id=1, company_id=1, is_active=False,
                  created_at=datetime(2024, 6, 1, tzinfo=timezone.utc))
    d3 = District(id=3, name="Downtown", city_id=2, company_id=2, is_active=True)
    d4 = District(id=4, name="Uptown", city_id=2, company_id=2, is_active=True)

    # district 1 allows user3 explicitly (different company)
    d1.allowed_users.append(user3)

    db_session.add_all([
        company1, company2, user1, user2, user3,
        country1, country2, city1, city2, d1, d2, d3, d4,
    ])
    await db_session.commit()

    yield {"companies": [company1, company2], "users": [user1, user2, user3],
           "countries": [country1, country2],
           "cities": [city1, city2], "districts": [d1, d2, d3, d4]}

    # Cleanup
    for obj in [d1, d2, d3, d4, city1, city2, country1, country2,
                user1, user2, user3, company1, company2]:
        await db_session.delete(obj)
    await db_session.commit()


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CitySchema(BaseModel):
    id: int
    name: str


class UserSchema(BaseModel):
    id: int
    name: str


class DistrictSchema(BaseModel):
    id: int
    name: str
    is_active: bool
    city_id: int
    city: CitySchema
    created_at: datetime | None = None
    created_by_id: int | None = None
    created_by: UserSchema | None = None
    updated_at: datetime | None = None
    updated_by_id: int | None = None
    updated_by: UserSchema | None = None


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


class TagSchema(BaseModel):
    id: int
    name: str
    slug: str
    code: str | None = None
    city_id: int


class TagCreateSchema(BaseModel):
    name: str
    slug: str
    code: str | None = None
    city_id: int


class TagUpdateSchema(BaseModel):
    name: str | None = None
    slug: str | None = None
    code: str | None = None
    city_id: int | None = None
