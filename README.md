# crudite

A declarative CRUD endpoint factory for **FastAPI** + **async SQLAlchemy 2.0**.

Declare once, get a fully-featured paginated list endpoint: filtering, sorting, search, nested joins, row-level permissions, and lifecycle hooks — no boilerplate.

> **Status:** List endpoint implemented. Create / update / delete coming next.

---

## Installation

```bash
pip install crudite
```

**Requirements:** Python ≥ 3.13, FastAPI ≥ 0.111, SQLAlchemy ≥ 2.0, Pydantic ≥ 2.0.

---

## Quick start

```python
from fastapi import APIRouter
from crudite import list_endpoint, ListConfig

router = APIRouter()

list_endpoint(
    router=router,
    path="/districts",
    model=District,
    schema=DistrictSchema,
    config=ListConfig(
        login_required=False,
        filterable_fields=["name", "is_active"],
        sortable_fields=["name", "created_at"],
        search_fields=["name"],
    ),
    get_db=get_db,
)
```

This registers `GET /districts` and immediately supports:

```
GET /districts?q=mar&sort=-name&page=2&items_per_page=20&is_active=true
```

---

## Full example

```python
# models.py
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class City(Base):
    __tablename__ = "cities"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    districts: Mapped[list["District"]] = relationship(back_populates="city")
    _order_fields = ("name",)

class District(Base):
    __tablename__ = "districts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    is_active: Mapped[bool] = mapped_column(default=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    tenant_id: Mapped[int | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)
    city: Mapped[City] = relationship(back_populates="districts")
    allowed_users: Mapped[list[User]] = relationship(secondary=district_allowed_users)
    _order_fields = ("name",)
```

```python
# schemas.py
from pydantic import BaseModel

class CitySchema(BaseModel):
    id: int
    name: str

class DistrictSchema(BaseModel):
    id: int
    name: str
    is_active: bool
    city_id: int
    city: CitySchema          # nested → auto-detected as joinedload
```

```python
# routes.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from crudite import list_endpoint, ListConfig

router = APIRouter()

def check_permissions(current_user, required: list[str]) -> bool:
    return all(p in current_user.permissions for p in required)

list_endpoint(
    router=router,
    path="/cities/{city_id}/districts",
    model=District,
    schema=DistrictSchema,
    config=ListConfig(
        # --- path params ---
        path_filters={"city_id": "city_id"},  # filter District.city_id == path city_id

        # --- auth ---
        login_required=True,
        login_dep=get_current_user,            # FastAPI dependency → current_user
        permissions=["erp:district:view"],
        permission_checker=check_permissions,

        # --- filtering ---
        filterable_fields=["name", "is_active", "city.name"],
        default_filters={"is_active": True},   # always applied, not user-controllable

        # --- sorting ---
        sortable_fields=["name", "city.name"],

        # --- search ---
        search_fields=["name"],

        # --- fastapi ---
        tags=["Districts"],
        summary="List districts for a city",
    ),
    get_db=get_db,
)
```

---

## Response format

All list endpoints return the same paginated envelope:

```json
{
  "data": [
    { "id": 1, "name": "Montmartre", "is_active": true, "city_id": 1, "city": { "id": 1, "name": "Paris" } }
  ],
  "total_count": 42,
  "has_more": true,
  "page": 1,
  "items_per_page": 25
}
```

---

## URL parameters reference

| Parameter | Example | Description |
|---|---|---|
| `sort` | `?sort=-name,city.name` | Comma-separated fields. Prefix `-` for DESC. Nested fields use `.` notation. Falls back to `model._order_fields`. |
| `page` | `?page=2` | Page number (1-based). Combined with `items_per_page`. |
| `items_per_page` | `?items_per_page=10` | Results per page. Default: 25. |
| `offset` | `?offset=50` | Offset-based pagination (alternative to page mode). |
| `limit` | `?limit=10` | Limit for offset pagination. |
| `q` | `?q=paris` | Global search — ILIKE across all `search_fields` (OR). |
| `count_only` | `?count_only=true` | Returns `{"total_count": N}` only, skipping data fetch. |
| `<field>` | `?is_active=true` | Filter on any whitelisted field. |
| `<field>__<op>` | `?name__ilike=%par%` | Filter with explicit operator (see below). |

### Filter operators

| Operator | SQL equivalent |
|---|---|
| *(none)* / `__eq` | `= value` |
| `__ne` | `!= value` |
| `__lt` / `__lte` | `< value` / `<= value` |
| `__gt` / `__gte` | `> value` / `>= value` |
| `__in` | `IN (v1, v2, ...)` — comma-separated values |
| `__like` | `LIKE value` — case-sensitive |
| `__ilike` | `ILIKE value` — case-insensitive |
| `__isnull` | `IS NULL` (`true`) or `IS NOT NULL` (`false`) |

Nested fields use dot notation: `?city.name__ilike=Par%`. The relationship must be in the Pydantic schema (auto-joined via `joinedload`).

---

## `ListConfig` reference

```python
@dataclass
class ListConfig:
    # Path parameters
    path_filters: dict[str, str]        # {"url_param": "model_field"}

    # Auth
    login_required: bool                # default True — 401 if no user
    login_dep: Callable | None          # FastAPI dependency returning current_user
    permissions: list[str]              # required permission strings
    permission_checker: Callable | None # (current_user, list[str]) -> bool

    # Filtering
    filterable_fields: list[str]        # plain or "rel.field"
    filter_fns: dict[str, FilterFn]     # field -> custom fn (overrides built-in logic)
    default_filters: dict[str, Any]     # always-applied, not exposed as URL params

    # Sorting
    sortable_fields: list[str]          # plain or "rel.field"

    # Search
    search_fields: list[str]            # fields for ?q= ILIKE search
    search_fn: SearchFn | None          # custom search fn (overrides search_fields)

    # Hooks
    before_query: HookFn | None         # (query, request, current_user) -> query
    after_query: AfterFn | None         # (rows, request, current_user) -> rows

    # FastAPI
    dependencies: list[Any]             # extra Depends() to attach to the route
    tags: list[str]
    summary: str | None
```

All callables may be **sync or async** — crudite detects and awaits accordingly.

---

## Auto-join detection

crudite inspects the Pydantic `schema` at registration time. Any field annotated with a `BaseModel` subclass is matched to a SQLAlchemy relationship by name:

- `field: RelatedSchema` → **many-to-one / one-to-one** → `joinedload`
- `field: list[RelatedSchema]` → **one-to-many** → `selectinload` (avoids cartesian products with pagination)

Nested fields (e.g. `city.name`) in `filterable_fields` or `sortable_fields` trigger an explicit `JOIN` on the related table and switch to `contains_eager` for that relationship.

---

## Permissions

crudite applies a two-layer permission model:

**1. Route-level** — checked once per request:
```python
permission_checker(current_user, config.permissions)  # must return True
```
Returns HTTP 403 on failure.

**2. Row-level** — auto-applied as SQL WHERE conditions (never raises, just filters rows):

| Model attribute | Condition added |
|---|---|
| `tenant_id` column | `model.tenant_id == current_user.tenant_id` |
| `allowed_users` relationship | `model.allowed_users.any(User.id == current_user.id)` |

When both are present, they combine with **OR** — a user sees a row if they belong to the right tenant *or* are explicitly in `allowed_users`.

---

## Custom filter functions

For complex filtering logic that can't be expressed with `field__operator=value`:

```python
from sqlalchemy.sql import Select

def active_this_week(query: Select, value: str, current_user) -> Select:
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=7)
    return query.where(MyModel.activated_at >= cutoff)

config = ListConfig(
    filterable_fields=["active_this_week"],
    filter_fns={"active_this_week": active_this_week},
)
```

Call: `GET /items?active_this_week=1`

---

## Hooks

```python
async def log_query(query: Select, request: Request, current_user) -> Select:
    logger.info("list query by %s", current_user.id)
    return query

def redact_sensitive(rows: list, request: Request, current_user) -> list:
    if not current_user.is_admin:
        for row in rows:
            row.secret = None
    return rows

config = ListConfig(
    before_query=log_query,
    after_query=redact_sensitive,
)
```

---

## Default sort

Every model should declare `_order_fields` as a tuple of column names. This is used when the client sends no `?sort=` parameter:

```python
class District(Base):
    ...
    _order_fields = ("name",)  # always sort by name ASC when no sort param given
```

Sort columns always use `NULLS LAST`.

---

## `list_endpoint()` signature

```python
def list_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    schema: type[BaseModel],
    config: ListConfig,
    *,
    get_db: Callable,           # FastAPI dependency returning AsyncSession
) -> None:
```

Join resolution and config validation run at **registration time** (once), not per request.
