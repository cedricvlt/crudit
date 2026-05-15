from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from fastapi import HTTPException
from sqlalchemy import Table, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase


@dataclass(frozen=True)
class ForeignKeySpec:
    """A single foreign-key relationship detected on a model."""

    column: str                   # local FK column name, e.g. "city_id"
    target_table: Table           # referenced SQLAlchemy Table
    target_pk: str                # referenced PK column name, e.g. "id"
    constraint_name: str | None   # for IntegrityError fallback


def detect_foreign_keys(
    model: type[DeclarativeBase],
) -> list[ForeignKeySpec]:
    """Inspect ``model.__table__`` once at registration time.

    Picks up every single-column ``ForeignKey`` declared on the table.
    Composite FKs (rare) are skipped silently — out of scope for the
    per-column pre-flight check. Duplicate references on the same column
    are de-duplicated.
    """
    seen: set[tuple[str, str, str]] = set()
    specs: list[ForeignKeySpec] = []

    for fk in model.__table__.foreign_keys:
        local_col = fk.parent.name
        target_table = fk.column.table
        target_pk = fk.column.name
        # Composite FKs have multiple columns on the same constraint;
        # we still emit one spec per column, which is fine for existence
        # checks on each individual referenced value.
        key = (local_col, target_table.name, target_pk)
        if key in seen:
            continue
        seen.add(key)
        constraint_name = fk.constraint.name if fk.constraint is not None else None
        specs.append(
            ForeignKeySpec(
                column=local_col,
                target_table=target_table,
                target_pk=target_pk,
                constraint_name=constraint_name,
            )
        )
    return specs


def _violation_exception(missing_cols: list[str]) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": "VALIDATION_ERROR",
            "message": "Validation failed",
            "fields": {col: ["Does not exist"] for col in missing_cols},
        },
    )


async def check_foreign_keys(
    db: AsyncSession,
    specs: list[ForeignKeySpec],
    values: Mapping[str, Any],
    *,
    skip_cols: Iterable[str] = (),
) -> None:
    """Pre-flight check: verify every relevant FK value points to an existing row.

    Runs a SINGLE SQL query containing N labeled scalar subqueries — one
    per FK that needs checking — so all references are validated in one
    round-trip. Raises ``HTTPException(422)`` listing every missing FK.

    Skipped specs:
      - any column in ``skip_cols`` (caller-controlled — e.g. parent_params,
        path_filters, or auto-set columns like created_by_id);
      - any column not present in ``values`` (the client didn't send it);
      - any column whose value is ``None`` (nothing to look up).
    """
    skip = frozenset(skip_cols)
    to_check = [
        s for s in specs
        if s.column not in skip
        and s.column in values
        and values[s.column] is not None
    ]
    if not to_check:
        return

    subqueries = []
    for spec in to_check:
        pk_col = spec.target_table.c[spec.target_pk]
        sq = (
            select(pk_col)
            .where(pk_col == values[spec.column])
            .limit(1)
            .scalar_subquery()
            .label(spec.column)
        )
        subqueries.append(sq)

    row = (await db.execute(select(*subqueries))).one()
    missing = [
        spec.column
        for spec, present in zip(to_check, row)
        if present is None
    ]
    if missing:
        raise _violation_exception(missing)


def integrity_error_to_http(
    err: IntegrityError,
    specs: list[ForeignKeySpec],
) -> HTTPException | None:
    """Translate an ``IntegrityError`` raised at ``commit()`` to HTTP 422.

    Best-effort: tries to match a known FK constraint name in the underlying
    driver's error text. Returns ``None`` if no spec matches so callers can
    chain multiple translators (unique → fk → generic).
    """
    msg = str(err.orig) if err.orig is not None else str(err)
    for spec in specs:
        if spec.constraint_name and spec.constraint_name in msg:
            return _violation_exception([spec.column])
    return None
