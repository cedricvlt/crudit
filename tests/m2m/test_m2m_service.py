"""Direct service-layer tests for the m2m services (no HTTP)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import delete

from crudit import (
    CruditContext,
    CruditNotFound,
    CruditValidationError,
    M2MConfig,
    M2MSpec,
    m2m_add_service,
    m2m_list_service,
    m2m_remove_service,
)
from crudit.joins import resolve_joins
from crudit.m2m.endpoint import _resolve_association_columns
from tests.conftest import District, User, district_allowed_users


class UserSchema(BaseModel):
    id: int
    name: str


def _make_spec(**config_kwargs) -> M2MSpec:
    parent_fk_col, child_fk_col = _resolve_association_columns(
        district_allowed_users, District, User
    )
    return M2MSpec(
        parent_model=District,
        child_model=User,
        association_table=district_allowed_users,
        child_schema=UserSchema,
        parent_fk_col=parent_fk_col,
        child_fk_col=child_fk_col,
        join_info=resolve_joins(User, UserSchema),
        config=M2MConfig(**config_kwargs),
        login_enforced=True,
    )


@pytest.fixture
async def _clean_links(db_session, seed):
    yield
    # Remove any link rows tests created beyond the seeded d1→user3 one.
    await db_session.execute(
        delete(district_allowed_users).where(
            ~(
                (district_allowed_users.c.district_id == 1)
                & (district_allowed_users.c.user_id == 3)
            )
        )
    )
    await db_session.commit()


async def test_m2m_add_list_remove_roundtrip(db_session, seed, _clean_links):
    user1 = seed["users"][0]  # Alice, company1 — d1 belongs to company1
    spec = _make_spec()
    ctx = CruditContext(user=user1)

    added = await m2m_add_service(db_session, ctx, spec=spec, parent_id=1, child_ids=[1])
    assert {u.id for u in added} == {1, 3}  # user3 seeded as allowed

    listed = await m2m_list_service(db_session, ctx, spec=spec, parent_id=1)
    assert {u.id for u in listed} == {1, 3}

    await m2m_remove_service(db_session, ctx, spec=spec, parent_id=1, child_ids=[1])
    listed = await m2m_list_service(db_session, ctx, spec=spec, parent_id=1)
    assert {u.id for u in listed} == {3}


async def test_m2m_parent_not_found(db_session, seed):
    ctx = CruditContext(user=seed["users"][0])
    spec = _make_spec()
    with pytest.raises(CruditNotFound):
        await m2m_list_service(db_session, ctx, spec=spec, parent_id=999)


async def test_m2m_parent_row_level_forbidden(db_session, seed):
    """A user from another company cannot drive M2M links on a scoped parent."""
    user2 = seed["users"][1]  # Bob, company2; d1 belongs to company1
    ctx = CruditContext(user=user2)
    spec = _make_spec()
    with pytest.raises(HTTPException) as exc_info:
        await m2m_add_service(db_session, ctx, spec=spec, parent_id=1, child_ids=[2])
    assert exc_info.value.status_code == 403


async def test_m2m_add_missing_child_ids(db_session, seed):
    ctx = CruditContext(user=seed["users"][0])
    spec = _make_spec()
    with pytest.raises(CruditValidationError) as exc_info:
        await m2m_add_service(db_session, ctx, spec=spec, parent_id=1, child_ids=[998, 999])
    assert "ids" in exc_info.value.fields
    assert "998" in exc_info.value.fields["ids"][0]


async def test_m2m_anonymous_forbidden_when_login_enforced(db_session, seed):
    ctx = CruditContext(user=None)
    spec = _make_spec()
    with pytest.raises(HTTPException) as exc_info:
        await m2m_list_service(db_session, ctx, spec=spec, parent_id=1)
    assert exc_info.value.status_code == 401
