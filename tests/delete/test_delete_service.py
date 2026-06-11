"""Direct service-layer tests for delete_service (no HTTP)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from crudit import CruditContext, CruditNotFound, DeleteConfig, delete_service
from tests.conftest import District


async def test_delete_service_happy_path(db_session, seed):
    user1 = seed["users"][0]
    extra = District(id=100, name="Doomed", city_id=1, company_id=1)
    db_session.add(extra)
    await db_session.commit()

    ctx = CruditContext(user=user1)
    await delete_service(db_session, ctx, model=District, config=DeleteConfig(), id=100)

    remaining = (
        await db_session.scalars(select(District).where(District.id == 100))
    ).one_or_none()
    assert remaining is None


async def test_delete_service_not_found(db_session, seed):
    ctx = CruditContext(user=seed["users"][0])
    with pytest.raises(CruditNotFound):
        await delete_service(db_session, ctx, model=District, config=DeleteConfig(), id=999)


async def test_delete_service_row_level_forbidden(db_session, seed):
    user2 = seed["users"][1]  # Bob, company2
    ctx = CruditContext(user=user2)
    with pytest.raises(HTTPException) as exc_info:
        await delete_service(db_session, ctx, model=District, config=DeleteConfig(), id=1)
    assert exc_info.value.status_code == 403


async def test_delete_service_fk_conflict_becomes_409(db_session, seed, monkeypatch):
    """An IntegrityError on commit (FK RESTRICT) surfaces as a structured 409."""
    user1 = seed["users"][0]
    extra = District(id=101, name="Referenced", city_id=1, company_id=1)
    db_session.add(extra)
    await db_session.commit()

    async def failing_commit():
        raise IntegrityError("DELETE", {}, Exception("FOREIGN KEY constraint failed"))

    rolled_back = []
    real_rollback = db_session.rollback

    async def tracking_rollback():
        rolled_back.append(True)
        await real_rollback()

    monkeypatch.setattr(db_session, "commit", failing_commit)
    monkeypatch.setattr(db_session, "rollback", tracking_rollback)

    ctx = CruditContext(user=user1)
    with pytest.raises(HTTPException) as exc_info:
        await delete_service(db_session, ctx, model=District, config=DeleteConfig(), id=101)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "DELETE_CONFLICT"
    assert rolled_back

    # Cleanup: the row is still there (delete was rolled back)
    monkeypatch.undo()
    obj = (await db_session.scalars(select(District).where(District.id == 101))).one()
    await db_session.delete(obj)
    await db_session.commit()
