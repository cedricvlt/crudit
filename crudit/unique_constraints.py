from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from fastapi import HTTPException
from sqlalchemy import UniqueConstraint, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


@dataclass(frozen=True)
class UniqueSpec:
    """A single unique constraint detected on a model."""

    name: str | None
    columns: tuple[str, ...]


def detect_unique_constraints(
    model: type[DeclarativeBase],
) -> list[UniqueSpec]:
    """Inspect ``model.__table__`` once at registration time.

    Picks up:
    - ``mapped_column(..., unique=True)`` (auto-translated by SQLAlchemy to a
      ``UniqueConstraint`` in ``Table.constraints``).
    - Explicit ``UniqueConstraint(..., name=...)`` in ``__table_args__``.
    - ``Index(..., unique=True)`` in ``__table_args__``.

    Skips the primary-key columns (already enforced) and de-duplicates by
    column tuple so a column-level ``unique=True`` plus a redundant
    ``UniqueConstraint`` on the same column is checked only once.
    """
    table = model.__table__
    pk_cols = frozenset(c.name for c in table.primary_key.columns)
    seen: set[tuple[str, ...]] = set()
    specs: list[UniqueSpec] = []

    for constraint in table.constraints:
        if not isinstance(constraint, UniqueConstraint):
            continue
        cols = tuple(c.name for c in constraint.columns)
        if not cols or frozenset(cols) == pk_cols or cols in seen:
            continue
        seen.add(cols)
        specs.append(UniqueSpec(name=constraint.name, columns=cols))

    for index in table.indexes:
        if not index.unique:
            continue
        cols = tuple(c.name for c in index.columns)
        if not cols or frozenset(cols) == pk_cols or cols in seen:
            continue
        seen.add(cols)
        specs.append(UniqueSpec(name=index.name, columns=cols))

    return specs


def _violation_exception(spec: UniqueSpec) -> HTTPException:
    detail: dict[str, Any] = {
        "code": "VALIDATION_ERROR",
        "message": "Validation failed",
        "fields": {col: ["Already exists"] for col in spec.columns},
    }
    return HTTPException(status_code=422, detail=detail)


async def check_unique_constraints(
    db: AsyncSession,
    model: type[DeclarativeBase],
    specs: list[UniqueSpec],
    values: Mapping[str, Any],
    *,
    exclude_pk: tuple[str, Any] | None = None,
) -> None:
    """Pre-flight check. Raises ``HTTPException(409)`` on the first violation.

    Skips a spec if any of its column values is ``None`` — SQL NULL semantics:
    NULLs do not conflict with each other in a unique constraint.
    """
    for spec in specs:
        col_values = [values.get(c) for c in spec.columns]
        if any(v is None for v in col_values):
            continue

        q = select(literal(1)).select_from(model)
        for col_name, val in zip(spec.columns, col_values):
            q = q.where(getattr(model, col_name) == val)
        if exclude_pk is not None:
            pk_name, pk_value = exclude_pk
            q = q.where(getattr(model, pk_name) != pk_value)

        result = await db.execute(q.limit(1))
        if result.scalar() is not None:
            raise _violation_exception(spec)


def integrity_error_to_http(
    err: IntegrityError,
    specs: list[UniqueSpec],
) -> HTTPException:
    """Translate an ``IntegrityError`` raised at ``commit()`` to HTTP 422.

    Best-effort: tries to match a known constraint name in the underlying
    driver's error text; otherwise returns a generic 422.
    """
    msg = str(err.orig) if err.orig is not None else str(err)
    for spec in specs:
        if spec.name and spec.name in msg:
            return _violation_exception(spec)
    return HTTPException(
        status_code=422,
        detail={"code": "VALIDATION_ERROR", "message": "Validation failed"},
    )
