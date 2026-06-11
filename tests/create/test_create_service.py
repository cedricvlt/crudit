"""Direct service-layer tests for create_service (no HTTP)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from crudit import (
    CreateConfig,
    CruditContext,
    CruditNotFound,
    CruditValidationError,
    ParentParam,
    create_service,
)
from tests.conftest import City, District


class DistrictCreateSchema(BaseModel):
    name: str
    city_id: int
    is_active: bool = True


class DistrictReadSchema(BaseModel):
    id: int
    name: str
    city_id: int
    is_active: bool
    created_by_id: int | None = None


class DistrictBodySchema(BaseModel):
    """Body without city_id — used with parent_params / path_filters."""

    name: str
    is_active: bool = True


@pytest.fixture(autouse=True)
async def _clean_created(db_session, seed):
    """Remove districts created by these tests before the seed teardown
    deletes the cities they reference (city_id is NOT NULL)."""
    yield
    from sqlalchemy import delete as sa_delete

    await db_session.execute(sa_delete(District).where(District.id > 4))
    await db_session.commit()


async def test_create_service_happy_path_with_audit(db_session, seed):
    user1 = seed["users"][0]
    ctx = CruditContext(user=user1)
    body = DistrictCreateSchema(name="ServiceDistrict", city_id=1)

    result = await create_service(
        db_session,
        ctx,
        model=District,
        body=body,
        read_schema=DistrictReadSchema,
        config=CreateConfig(),
    )

    assert result.name == "ServiceDistrict"
    assert result.city_id == 1
    # Audit autofill from ctx.user
    assert result.created_by_id == user1.id


async def test_create_service_parent_params_from_ctx_path_params(db_session, seed):
    user1 = seed["users"][0]
    config = CreateConfig(
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    ctx = CruditContext(user=user1, path_params={"city_id": 2})

    result = await create_service(
        db_session,
        ctx,
        model=District,
        body=DistrictBodySchema(name="NestedDistrict"),
        read_schema=DistrictReadSchema,
        config=config,
    )
    assert result.city_id == 2


async def test_create_service_missing_parent_path_param(db_session, seed):
    config = CreateConfig(
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    ctx = CruditContext(user=seed["users"][0], path_params={})

    with pytest.raises(CruditValidationError, match="city_id"):
        await create_service(
            db_session,
            ctx,
            model=District,
            body=DistrictBodySchema(name="X"),
            read_schema=DistrictReadSchema,
            config=config,
        )


async def test_create_service_parent_not_found(db_session, seed):
    config = CreateConfig(
        parent_params=[ParentParam(url_param="city_id", model=City, child_field="city_id")],
    )
    ctx = CruditContext(user=seed["users"][0], path_params={"city_id": 999})

    with pytest.raises(CruditNotFound):
        await create_service(
            db_session,
            ctx,
            model=District,
            body=DistrictBodySchema(name="X"),
            read_schema=DistrictReadSchema,
            config=config,
        )


async def test_create_service_login_required_without_user(db_session, seed):
    ctx = CruditContext(user=None)
    with pytest.raises(HTTPException) as exc_info:
        await create_service(
            db_session,
            ctx,
            model=District,
            body=DistrictCreateSchema(name="X", city_id=1),
            read_schema=DistrictReadSchema,
            config=CreateConfig(login_required=True),
        )
    assert exc_info.value.status_code == 401


async def test_create_service_hooks_share_shim_request_state(db_session, seed):
    """Outside HTTP, hooks receive a request shim exposing path_params and a
    state namespace shared between before/after hooks of the same call."""
    seen: dict = {}

    def before_create(obj, request, current_user):
        seen["path_params"] = dict(request.path_params)
        request.state.marker = "from-before"
        return obj

    def after_create(obj, request, current_user):
        seen["state_marker"] = getattr(request.state, "marker", None)
        return obj

    config = CreateConfig(before_create=before_create, after_create=after_create)
    ctx = CruditContext(user=seed["users"][0], path_params={"foo": "bar"})

    await create_service(
        db_session,
        ctx,
        model=District,
        body=DistrictCreateSchema(name="HookDistrict", city_id=1),
        read_schema=DistrictReadSchema,
        config=config,
    )

    assert seen["path_params"] == {"foo": "bar"}
    assert seen["state_marker"] == "from-before"
