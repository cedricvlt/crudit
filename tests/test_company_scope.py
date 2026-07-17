"""Company scoping only applies when ``company_id`` really is the tenant FK.

Scoping keys off the attribute *name* ``company_id``, so a model that reuses that
name for an unrelated foreign key must not be silently filtered down to zero rows.
These models live on their own ``Base`` to keep them out of the shared metadata.
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from crudit.permissions import _build_object_level_checks, _company_scope_condition


class Base(DeclarativeBase):
    pass


scope_user_companies = Table(
    "scope_user_companies",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("scope_users.id"), primary_key=True),
    Column("company_id", Integer, ForeignKey("scope_companies.id"), primary_key=True),
)


class Company(Base):
    __tablename__ = "scope_companies"

    id: Mapped[int] = mapped_column(primary_key=True)


class Contact(Base):
    __tablename__ = "scope_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)


class User(Base):
    __tablename__ = "scope_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    companies: Mapped[list[Company]] = relationship(
        "Company", secondary=scope_user_companies, lazy="selectin"
    )


class Tenanted(Base):
    """The ordinary case: ``company_id`` is a real FK to the tenant table."""

    __tablename__ = "scope_tenanted"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("scope_companies.id"))


class ContactLink(Base):
    """The collision: ``company_id`` points at a contact, not at the tenant table."""

    __tablename__ = "scope_contact_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("scope_contacts.id"))


class LooseCompanyId(Base):
    """``company_id`` with no FK at all — undeterminable, so it must stay scoped."""

    __tablename__ = "scope_loose"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int | None] = mapped_column(Integer)


class PlainUser:
    """A non-mapped user object — nothing can be proven, so scoping must hold."""

    def __init__(self) -> None:
        self.id = 1
        self.companies = [Company(id=1)]


def test_real_tenant_fk_is_scoped():
    condition = _company_scope_condition(Tenanted, User(id=1, companies=[Company(id=1)]))
    assert condition is not None


def test_company_id_pointing_elsewhere_is_not_scoped():
    condition = _company_scope_condition(ContactLink, User(id=1, companies=[Company(id=1)]))
    assert condition is None


def test_company_id_without_fk_stays_scoped():
    condition = _company_scope_condition(LooseCompanyId, User(id=1, companies=[Company(id=1)]))
    assert condition is not None


def test_unmapped_user_stays_scoped():
    condition = _company_scope_condition(Tenanted, PlainUser())
    assert condition is not None


def test_model_without_company_id_is_not_scoped():
    condition = _company_scope_condition(Company, User(id=1, companies=[Company(id=1)]))
    assert condition is None


def test_object_level_check_skipped_when_company_id_points_elsewhere():
    user = User(id=1, companies=[Company(id=1)])
    assert _build_object_level_checks(ContactLink, user) == []
    assert len(_build_object_level_checks(Tenanted, user)) == 1
