"""Direct service-layer tests for update_service (no HTTP)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from crudit import CruditContext, CruditNotFound, UpdateConfig, update_service
from tests.conftest import District


class DistrictUpdateSchema(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class DistrictReadSchema(BaseModel):
    id: int
    name: str
    is_active: bool
    updated_by_id: int | None = None


async def test_update_service_exclude_unset_semantics(db_session, seed):
    """A partial built with model_validate only patches the provided keys —
    same exclude_unset semantics as the HTTP endpoint."""
    user1 = seed["users"][0]
    ctx = CruditContext(user=user1)
    # d2 is inactive; patch only the name and is_active must stay False.
    body = DistrictUpdateSchema.model_validate({"name": "Renamed"})

    result = await update_service(
        db_session,
        ctx,
        model=District,
        body=body,
        read_schema=DistrictReadSchema,
        config=UpdateConfig(),
        id=2,
    )

    assert result.name == "Renamed"
    assert result.is_active is False
    assert result.updated_by_id == user1.id


async def test_update_service_not_found(db_session, seed):
    ctx = CruditContext(user=seed["users"][0])
    with pytest.raises(CruditNotFound):
        await update_service(
            db_session,
            ctx,
            model=District,
            body=DistrictUpdateSchema.model_validate({"name": "X"}),
            read_schema=DistrictReadSchema,
            config=UpdateConfig(),
            id=999,
        )


async def test_update_service_row_level_forbidden(db_session, seed):
    """A user from another company cannot update a company-scoped row."""
    user2 = seed["users"][1]  # Bob, company2
    ctx = CruditContext(user=user2)
    with pytest.raises(HTTPException) as exc_info:
        await update_service(
            db_session,
            ctx,
            model=District,
            body=DistrictUpdateSchema.model_validate({"name": "Hacked"}),
            read_schema=DistrictReadSchema,
            config=UpdateConfig(),
            id=1,  # d1 belongs to company1
        )
    assert exc_info.value.status_code == 403
