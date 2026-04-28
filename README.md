# crudit

A declarative CRUD endpoint factory for **FastAPI** + **async SQLAlchemy 2.0**.

Declare once, get a fully-featured endpoint: filtering, sorting, search, nested joins, row-level permissions, and lifecycle hooks — no boilerplate.

> **Status:** List, read, create, update, delete, reorder, options, and many-to-many endpoints implemented.

---

## Installation

```bash
pip install crudit
```

**Requirements:** Python ≥ 3.12, FastAPI ≥ 0.111, SQLAlchemy ≥ 2.0, Pydantic ≥ 2.0.

---

## Quick start

```python
from fastapi import APIRouter
from crudit import list_endpoint, ListConfig, read_endpoint, ReadConfig

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

read_endpoint(
    router=router,
    path="/districts/{id}",
    model=District,
    schema=DistrictSchema,
    config=ReadConfig(login_required=False),
    get_db=get_db,
)
```

This registers:

```
GET /districts?q=mar&sort=-name&page=2&itemsPerPage=20&is_active=true
GET /districts/42
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
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True)
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
from crudit import list_endpoint, ListConfig, read_endpoint, ReadConfig, create_endpoint, CreateConfig, ParentParam, update_endpoint, UpdateConfig, delete_endpoint, DeleteConfig, reorder_endpoint, ReorderConfig

router = APIRouter()

async def permission_dep(current_user=Depends(get_current_user)):
    """Raise 403 when the user lacks the required permissions."""
    if not all(p in current_user.permissions for p in REQUIRED_PERMISSIONS):
        raise HTTPException(status_code=403)

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
        permissions=["erp:district:view"],

        # --- filtering ---
        filterable_fields=["name", "is_active", "city.name"],
        default_filters={"is_active": True},   # always applied, not user-controllable

        # --- sorting ---
        sortable_fields=["name", "city.name"],

        # --- search ---
        search_fields=["name"],

        # --- fastapi ---
        tags=["Districts"],
    ),
    login_dep=get_current_user,            # FastAPI dependency → current_user
    permission_dep=permission_dep,         # plain async callable, wrapped with Depends()
    summary="List districts for a city",
    get_db=get_db,
)

read_endpoint(
    router=router,
    path="/districts/{id}",
    model=District,
    schema=DistrictSchema,
    config=ReadConfig(
        login_required=True,
        permissions=["erp:district:view"],
        tags=["Districts"],
    ),
    login_dep=get_current_user,
    permission_dep=permission_dep,
    summary="Get a district by ID",
    get_db=get_db,
)

create_endpoint(
    router=router,
    path="/cities/{city_id}/districts",
    model=District,
    create_schema=DistrictCreateSchema,   # input body schema
    read_schema=DistrictSchema,           # response schema (with joins)
    config=CreateConfig(
        parent_params=[
            ParentParam(url_param="city_id", model=City, child_field="city_id"),
        ],
        login_required=True,
        permissions=["erp:district:edit"],
        tags=["Districts"],
    ),
    login_dep=get_current_user,
    permission_dep=permission_dep,
    summary="Create a district in a city",
    get_db=get_db,
)

update_endpoint(
    router=router,
    path="/districts/{id}",
    model=District,
    update_schema=DistrictUpdateSchema,   # partial input body schema (all fields optional)
    read_schema=DistrictSchema,           # response schema (with joins)
    config=UpdateConfig(
        login_required=True,
        permissions=["erp:district:edit"],
        tags=["Districts"],
    ),
    login_dep=get_current_user,
    permission_dep=permission_dep,
    summary="Partially update a district",
    get_db=get_db,
)

delete_endpoint(
    router=router,
    path="/districts/{id}",
    model=District,
    config=DeleteConfig(
        login_required=True,
        permissions=["erp:district:delete"],
        tags=["Districts"],
    ),
    login_dep=get_current_user,
    permission_dep=permission_dep,
    summary="Delete a district",
    get_db=get_db,
)

reorder_endpoint(
    router=router,
    path="/cities/{city_id}/districts/reorder",
    model=District,
    config=ReorderConfig(
        path_filters={"city_id": "city_id"},
        login_required=True,
        permissions=["erp:district:edit"],
        tags=["Districts"],
    ),
    login_dep=get_current_user,
    permission_dep=permission_dep,
    summary="Reorder districts within a city",
    get_db=get_db,
)
```

---

## crud_router

`crud_router` is a one-call alternative to registering each endpoint individually. It returns a FastAPI `APIRouter` pre-configured with the five core CRUD verbs by default.

```python
from fastapi import FastAPI
from crudit import crud_router, SharedConfig

app = FastAPI()

router = crud_router(
    model=District,

    # --- schemas ---
    list_item_schema=DistrictSchema,       # GET  /         (list)
    read_schema=DistrictSchema,            # GET  /{id}     (read + create/update output)
    create_schema=DistrictCreateSchema,    # POST /         (create input)
    update_schema=DistrictUpdateSchema,    # PATCH /{id}    (update input)
    option_schema=DistrictSchema,          # GET  /options  (join resolution only)

    # --- db dependency ---
    get_db=get_db,

    # --- auth/FastAPI fields shared across all endpoints ---
    login_dep=get_current_user,
    permission_dep=permission_dep,         # plain async callable, wrapped with Depends()
    tags=["Districts"],

    # --- shared auth defaults (applied to every verb without an explicit config) ---
    shared=SharedConfig(
        login_required=True,
        permissions=["erp:district:view"],
    ),
)

app.include_router(router, prefix="/districts")
```

This registers:

```
GET     /districts              list
GET     /districts/{id}         read
POST    /districts              create
PATCH   /districts/{id}         update
DELETE  /districts/{id}         delete
```

### Adding options and reorder

`options` and `reorder` are opt-in via `extra_endpoints`:

```python
router = crud_router(
    model=District,
    list_item_schema=DistrictSchema,
    read_schema=DistrictSchema,
    create_schema=DistrictCreateSchema,
    update_schema=DistrictUpdateSchema,
    get_db=get_db,
    extra_endpoints=["options", "reorder"],
    shared=SharedConfig(login_required=False),
)
```

No `OptionsConfig` is needed — it defaults to `label_field="name"`. Pass an explicit `options=OptionsConfig(...)` to customise the label or any other field. Pass `option_schema=MySchema` when the options endpoint needs join resolution (e.g. for `label_fn` or filter/sort on related fields); defaults to a minimal schema with `name: str`.

### Restricting core endpoints

Pass `crud_endpoints` to register only a subset of the five core verbs:

```python
router = crud_router(
    model=District,
    list_item_schema=DistrictSchema,
    read_schema=DistrictSchema,
    get_db=get_db,
    crud_endpoints=["list", "read"],
    shared=SharedConfig(login_required=False),
)
```

Valid `crud_endpoints` values: `list`, `read`, `create`, `update`, `delete`.
Valid `extra_endpoints` values: `options`, `reorder`.

### Top-level auth arguments

`login_dep`, `permission_dep`, and `tags` are declared at the `crud_router` level because they are always the same for every endpoint on a given router:

| Argument | Type | Default | Description |
|---|---|---|---|
| `login_dep` | `Callable \| None` | `None` | FastAPI dependency returning `current_user` |
| `permission_dep` | `Callable \| None` | `None` | Plain async callable — wrapped with `Depends()` for route-level permission check |
| `tags` | `list[str] \| None` | `None` | OpenAPI tags applied to all registered routes |

### SharedConfig

`SharedConfig` sets auth defaults for every verb that does not have an explicit per-verb config:

| Field | Type | Default |
|---|---|---|
| `login_required` | `bool` | `True` |
| `permissions` | `list[str]` | `[]` |
| `dependencies` | `list[Any]` | `[]` |

### Per-verb config overrides

When you pass a per-verb config, it is used **as-is** — `shared` is ignored for that verb. This lets you deviate from the shared baseline for individual verbs:

```python
router = crud_router(
    model=District,
    list_item_schema=DistrictSchema,
    read_schema=DistrictSchema,
    create_schema=DistrictCreateSchema,
    update_schema=DistrictUpdateSchema,
    get_db=get_db,
    login_dep=get_current_user,
    shared=SharedConfig(login_required=True),
    # override: list is public, everything else requires auth
    list=ListConfig(login_required=False),
)
```

### Schema routing

| Verb | Input schema | Output schema |
|---|---|---|
| list | — | `list_item_schema` |
| read | — | `read_schema` |
| create | `create_schema` | `read_schema` |
| update | `update_schema` | `read_schema` |
| delete | — | — (204) |
| options | — | `OptionItem` (label from `OptionsConfig`, defaults to `"name"`); join resolution uses `option_schema` |
| reorder | `{ids: [...]}` | — (204) |

### Notes

- `options` defaults to `label_field="name"` when no `OptionsConfig` is provided. Pass `options=OptionsConfig(label_field="...")` or `options=OptionsConfig(label_fn=...)` to customise.
- `reorder` requires the model to have a `sort_order` column.
- Paths are always relative to the router prefix set in `app.include_router(..., prefix=...)`.

---

## Create endpoint

`create_endpoint` registers a `POST` route that validates the request body, auto-completes system fields, persists the object, and returns it as the read schema with **HTTP 201**.

### Schemas

Two separate schemas are required:

```python
class DistrictCreateSchema(BaseModel):
    name: str
    is_active: bool = True
    # city_id is intentionally absent — set from the path param

class DistrictSchema(BaseModel):   # reuse the read schema
    id: int
    name: str
    is_active: bool
    city_id: int
    city: CitySchema       # joined relationship — loaded automatically
```

### Parent path parameters

`parent_params` maps URL parameters to parent models. For each entry, crudit:

1. Reads the path parameter value
2. Queries the parent model and returns **404** if not found
3. Runs the same route-level and row-level permission checks on the parent
4. Sets the corresponding FK field on the new object (overriding any body value)

```python
ParentParam(
    url_param="city_id",   # name of the FastAPI path parameter
    model=City,            # parent SQLAlchemy model to fetch
    child_field="city_id", # FK field to set on the new object
)
```

Multiple parents are supported (e.g. `/companies/{company_id}/cities/{city_id}/districts`).

### Auto-complete fields

| Field | Condition | Value |
|---|---|---|
| `created_at` | column exists and has no `server_default` | `datetime.now(timezone.utc)` |
| `created_by` | column exists and user is authenticated | `current_user.id` |

### Field setters

For any field that needs custom logic, provide a setter callable in `field_setters`. Setters run after the built-in auto-complete and may be sync or async.

```python
def set_company(obj, request, current_user):
    return current_user.company_id

async def set_slug(obj, request, current_user):
    return slugify(obj.name)

CreateConfig(
    field_setters={
        "company_id": set_company,  # (obj, request, current_user) -> value
        "slug": set_slug,
    },
)
```

### Hooks

```python
def before(obj, request, current_user):
    obj.name = obj.name.strip()
    return obj

async def after(obj, request, current_user):
    await notify_created(obj.id)
    return obj

CreateConfig(
    before_create=before,   # (obj, request, current_user) -> obj  — before db.add()
    after_create=after,     # (obj, request, current_user) -> obj  — after commit, before response
)
```

`before_create` receives the unsaved ORM object and may mutate or replace it. `after_create` receives the reloaded object (with all relationships) after the transaction has committed.

### Execution order

For each POST request, crudit executes the following steps in order:

1. Route-level auth / permission check
2. Parent lookup + 404 check + parent permission check (for each `parent_params` entry)
3. Parse and validate body with `create_schema`
4. Build ORM object from body
5. Set parent FK fields
6. Auto-fill `created_at` (if applicable)
7. Auto-fill `created_by` (if applicable)
8. Run `field_setters`
9. Call `before_create` hook
10. `db.add(obj)` + `await db.commit()`
11. Reload object with eager-loaded relationships (from `read_schema`)
12. Call `after_create` hook
13. Return `read_schema.model_validate(obj)` with **HTTP 201**

---

## Update endpoint

`update_endpoint` registers a `PATCH` route that partially updates an existing object and returns it as the read schema with **HTTP 200**.

Only fields present in the request body are applied (`exclude_unset` semantics). Fields absent from the body are left unchanged.

### Schemas

Two separate schemas are required:

```python
class DistrictUpdateSchema(BaseModel):
    name: str | None = None        # all fields optional for PATCH
    is_active: bool | None = None

class DistrictSchema(BaseModel):   # reuse the read schema
    id: int
    name: str
    is_active: bool
    city_id: int
    city: CitySchema               # joined relationship — loaded automatically
    updated_at: datetime | None = None
    updated_by: int | None = None
```

### Auto-complete fields

| Field | Condition | Value |
|---|---|---|
| `updated_at` | column exists and has no `server_default` | `datetime.now(timezone.utc)` |
| `updated_by` | column exists and user is authenticated | `current_user.id` |

Auto-complete fields are injected into the patch dict before field setters and the `before_update` hook run, so they can be inspected or overridden.

### Field setters

Identical interface to `CreateConfig.field_setters`. Setters receive the **existing** ORM object, the request, and the current user. Their return value is merged into the patch dict.

```python
UpdateConfig(
    field_setters={"last_modified_by_ip": lambda obj, req, user: req.client.host},
)
```

### Hooks

```python
def before(obj, patch_data, request, current_user):
    if "name" in patch_data:
        patch_data["name"] = patch_data["name"].strip()
    return patch_data   # must return the (possibly modified) patch dict

async def after(obj, request, current_user):
    await notify_updated(obj.id)
    return obj

UpdateConfig(
    before_update=before,  # (obj, patch_data, request, current_user) -> patch_data
    after_update=after,    # (obj, request, current_user) -> obj
)
```

`before_update` receives the **existing** ORM object (before any changes) and the full patch dict (body fields + auto-complete + setters). It must return the patch dict. `after_update` receives the reloaded object after the transaction has committed.

### Execution order

For each PATCH request, crudit executes the following steps in order:

1. Route-level auth / permission check
2. Fetch object by PK — returns **404** if not found
3. Object-level permission check (`company_id` / `allowed_users`)
4. Parse body with `update_schema` → `patch_data` (only fields the client sent)
5. Auto-fill `updated_at` into `patch_data` (if applicable)
6. Auto-fill `updated_by` into `patch_data` (if applicable)
7. Run `field_setters` → merge results into `patch_data`
8. Call `before_update(obj, patch_data, request, current_user) -> patch_data`
9. Apply `patch_data` to ORM object (`setattr` for each key)
10. `db.add(obj)` + `await db.commit()`
11. Reload object with eager-loaded relationships (from `read_schema`)
12. Call `after_update(obj, request, current_user) -> obj`
13. Return `read_schema.model_validate(obj)` with **HTTP 200**

---

## Delete endpoint

`delete_endpoint` registers a `DELETE` route that removes an existing object and returns **204 No Content**.

### Hooks

```python
def before(obj, request, current_user):
    if obj.is_protected:
        raise HTTPException(status_code=409, detail="Object is protected.")

async def after(obj, request, current_user):
    await audit_log.record_deletion(obj.id, current_user.id)

DeleteConfig(
    before_delete=before,  # (obj, request, current_user) -> None  — runs before db.delete(); raise to abort
    after_delete=after,    # (obj, request, current_user) -> None  — runs after commit; obj is detached but attributes are still readable
)
```

`before_delete` receives the ORM object before deletion. Raise any exception (e.g. `HTTPException`) to abort the operation — nothing is deleted. `after_delete` receives the same ORM object after the transaction has committed; the object is detached from the session but its Python attributes remain accessible for logging or notifications.

### Execution order

For each DELETE request, crudit executes the following steps in order:

1. Route-level auth / permission check
2. Fetch object by PK — returns **404** if not found
3. Object-level permission check (`company_id` / `allowed_users`)
4. Call `before_delete(obj, request, current_user)` — raise to abort
5. `await db.delete(obj)` + `await db.commit()`
6. Call `after_delete(obj, request, current_user)`
7. Return **HTTP 204 No Content**

---

## Reorder endpoint

`reorder_endpoint` registers a `POST` route that sets `sort_order` on a batch of objects in the requested sequence and returns **204 No Content**.

The model must have a `sort_order` column. Positions are 0-based and assigned in the order of the `ids` array. Only the objects listed in `ids` are updated — other rows in the collection are left unchanged.

### Input format

```json
{ "ids": [3, 1, 4, 2] }
```

Objects are assigned `sort_order = 0, 1, 2, 3` respectively. An empty `ids` list succeeds immediately with 204.

### Path filters

Use `path_filters` to scope the reorder to a nested collection, exactly as in `ListConfig`:

```python
reorder_endpoint(
    router=router,
    path="/cities/{city_id}/districts/reorder",
    model=District,
    config=ReorderConfig(
        path_filters={"city_id": "city_id"},  # WHERE city_id = :city_id
        ...
    ),
    get_db=get_db,
)
```

Any ID that exists in the database but belongs to a different scope (e.g. a district in another city) is treated as not found and returns **404**.

### Hooks

```python
def before(objects, request, current_user):
    if any(obj.is_locked for obj in objects):
        raise HTTPException(status_code=409, detail="Cannot reorder locked items.")

async def after(objects, request, current_user):
    await broadcast_reorder([obj.id for obj in objects])

ReorderConfig(
    before_reorder=before,  # (objects, request, current_user) -> None — raise to abort
    after_reorder=after,    # (objects, request, current_user) -> None — after commit
)
```

`before_reorder` receives the ordered list of ORM objects before any `sort_order` assignment. Raise any exception to abort — no changes are written. `after_reorder` receives the same objects after the commit; their `sort_order` attributes reflect the new positions.

### Execution order

For each POST request, crudit executes the following steps in order:

1. Route-level auth / permission check
2. Fetch all objects matching `ids` + path filters — returns **404** if any are missing or out of scope
3. Object-level permission check (`company_id` / `allowed_users`) — returns **403** for inaccessible objects
4. Call `before_reorder(objects, request, current_user)` — raise to abort
5. Assign `sort_order = position index` for each object in order
6. `await db.commit()`
7. Call `after_reorder(objects, request, current_user)`
8. Return **HTTP 204 No Content**

---

## Delete endpoint response format

Delete endpoints return an empty body with **HTTP 204 No Content**.

Status codes:
- **204** — object deleted successfully
- **401** — `login_required=True` and no authenticated user
- **403** — user authenticated but fails route-level or row-level permission check
- **404** — no object with that primary key exists

---

## Create endpoint response format

Create endpoints return the created object serialised as `read_schema` (same structure as the read endpoint), with all joined relationships loaded:

```json
{ "id": 5, "name": "Pigalle", "is_active": true, "city_id": 1, "city": { "id": 1, "name": "Paris" } }
```

Status codes:
- **201** — object created successfully
- **400** — missing required path parameter
- **401** — `login_required=True` and no authenticated user
- **403** — user authenticated but fails route-level or parent row-level permission check
- **404** — a declared parent object was not found
- **422** — request body failed schema validation

---

## Update endpoint response format

Update endpoints return the updated object serialised as `read_schema`, with all joined relationships loaded:

```json
{ "id": 1, "name": "Renamed", "is_active": true, "city_id": 1, "city": { "id": 1, "name": "Paris" }, "updated_at": "2026-04-26T10:00:00Z", "updated_by": 1 }
```

Status codes:
- **200** — object updated successfully
- **401** — `login_required=True` and no authenticated user
- **403** — user authenticated but fails route-level or row-level permission check
- **404** — no object with that primary key exists
- **422** — request body failed schema validation

---

## Read endpoint response format

Read endpoints return the schema directly (no envelope):

```json
{ "id": 1, "name": "Montmartre", "is_active": true, "city_id": 1, "city": { "id": 1, "name": "Paris" } }
```

Status codes:
- **200** — object found and accessible
- **401** — `login_required=True` and no authenticated user
- **403** — user authenticated but fails route-level or row-level permission check
- **404** — no object with that primary key exists

> Unlike the list endpoint (which silently filters out inaccessible rows), the read endpoint distinguishes between "does not exist" (404) and "exists but you cannot see it" (403).

---

## Options endpoint response format

Options endpoints return an offset-paginated envelope with only `id` and `label` per item. Unlike the list endpoint, `page` and `itemsPerPage` are not included — only offset/limit-based pagination is supported.

```json
{
  "data": [
    { "id": 1, "label": "Paris — Montmartre" },
    { "id": 2, "label": "Paris — Marais" }
  ],
  "totalCount": 2,
  "hasMore": false
}
```

`label` is always a `str`. `id` reflects the model's primary key type. Use `?offset=` and `?limit=` for pagination.

---

## List endpoint response format

All list endpoints return the same paginated envelope:

```json
{
  "data": [
    { "id": 1, "name": "Montmartre", "is_active": true, "city_id": 1, "city": { "id": 1, "name": "Paris" } }
  ],
  "totalCount": 42,
  "hasMore": true,
  "page": 1,
  "itemsPerPage": 
}
```

---

## URL parameters reference

| Parameter | Example | Description                                                                                                       |
|---|---|-------------------------------------------------------------------------------------------------------------------|
| `sort` | `?sort=-name,city.name` | Comma-separated fields. Prefix `-` for DESC. Nested fields use `.` notation. Falls back to `model._order_fields`. |
| `page` | `?page=2` | Page number (1-based). Combined with `itemsPerPage`.                                                              |
| `itemsPerPage` | `?itemsPerPage=10` | Results per page. Default: 20.                                                                                    |
| `offset` | `?offset=50` | Offset-based pagination (alternative to page mode).                                                               |
| `limit` | `?limit=10` | Limit for offset pagination.                                                                                      |
| `q` | `?q=paris` | Global search — ILIKE across all `search_fields` (OR).                                                            |
| `countOnly` | `?countOnly=true` | Returns `{"totalCount": N}` only, skipping data fetch.                                                            |
| `<field>` | `?is_active=true` | Filter on any whitelisted field.                                                                                  |
| `<field>__<op>` | `?name__ilike=%par%` | Filter with explicit operator (see below).                                                                        |

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

All filter params — including operator-suffixed variants — are fully typed in the OpenAPI schema based on the SQLAlchemy column type. For example, `age__gte` is documented as `integer`, `created_at__lte` as `date`, and `name__isnull` as `boolean`. This means Swagger UI and generated clients show the correct input types with no extra configuration.

### Date period filters

Five additional operators collapse an entire time period into a `>= start AND < end` range. They work on both `date` and `datetime` columns (datetime columns use UTC-aware bounds automatically).

| Operator | Value format | Example |
|---|---|---|
| `__year` | `YYYY` | `?created_at__year=2024` |
| `__quarter` | `YYYY-Q[1-4]` | `?created_at__quarter=2024-Q3` |
| `__month` | `YYYY-MM` | `?created_at__month=2024-06` |
| `__week` | `YYYY-Www` (ISO 8601) | `?created_at__week=2024-W11` |
| `__relative` | keyword (see below) | `?created_at__relative=last-month` |

Supported `__relative` keywords: `today`, `yesterday`, `this-week`, `last-week`, `this-month`, `last-month`, `this-quarter`, `last-quarter`, `this-year`, `last-year`.

Invalid period values return **400**.

---

## Auto-join detection

crudit inspects the Pydantic `schema` at registration time. Any field annotated with a `BaseModel` subclass is matched to a SQLAlchemy relationship by name:

- `field: RelatedSchema` → **many-to-one / one-to-one** → `joinedload`
- `field: list[RelatedSchema]` → **one-to-many** → `selectinload` (avoids cartesian products with pagination)

Nested fields (e.g. `city.name`) in `filterable_fields` or `sortable_fields` trigger an explicit `JOIN` on the related table and switch to `contains_eager` for that relationship.

---

## Permissions

crudit applies a two-layer permission model on both list and read endpoints.

**1. Route-level** — a plain async callable injected at registration time via `Depends()`:
```python
# permission_dep is a plain async callable — crudit wraps it with Depends() automatically.
async def permission_dep(current_user=Depends(get_current_user)):
    if not all(p in current_user.permissions for p in REQUIRED_PERMISSIONS):
        raise HTTPException(status_code=403)

list_endpoint(
    ...,
    config=ListConfig(permissions=["erp:district:view"]),
    permission_dep=permission_dep,
    ...,
)
```

**2. Row-level** — auto-detected from model attributes:

| Model attribute | Condition |
|---|---|
| `company_id` column | user's `company_id` must match the row's `company_id` |
| `allowed_users` relationship | user's `id` must appear in the row's `allowed_users` |

When both are present they combine with **OR** — a row is accessible if the company matches *or* the user is explicitly listed.

The enforcement mechanism differs by endpoint:

| Endpoint | Row-level enforcement |
|---|---|
| `list_endpoint` | SQL `WHERE` clause — inaccessible rows are silently excluded |
| `read_endpoint` | Python check after fetch — returns **403** if the object exists but is inaccessible |

For `read_endpoint`, `allowed_users` is always `selectinload`-ed (even if absent from the response schema) so the membership check always has the data it needs.

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

All hooks may be **sync or async** — crudit detects and awaits accordingly.

### List / options endpoint hooks

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
    before_query=log_query,   # (query, request, current_user) -> query
    after_query=redact_sensitive,  # (rows, request, current_user) -> rows
)
```

The same hooks apply to `OptionsConfig`. `after_query` receives ORM model instances — after the hook the endpoint converts them to `{id, label}` items.

### Read endpoint hooks

```python
async def log_read(query: Select, request: Request, current_user) -> Select:
    logger.info("read query by %s", current_user.id)
    return query

def redact_single(row, request: Request, current_user):
    if not current_user.is_admin:
        row.secret = None
    return row

config = ReadConfig(
    before_query=log_read,    # (query, request, current_user) -> query
    after_query=redact_single,  # (row, request, current_user) -> row
)
```

`before_query` runs before the database call. `after_query` receives the ORM object after the permission check passes, before serialization.

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

## `OptionsConfig` reference

```python
@dataclass
class OptionsConfig:
    # Label — at most one may be set; defaults to label_field="name" when neither is provided
    label_field: str | None          # model column name used as the label
    label_fn: LabelFn | None         # (row) -> str — callable for computed labels

    # Path parameters
    path_filters: dict[str, str]     # {"url_param": "model_field"}

    # Auth
    login_required: bool             # default True — 401 if no user
    permissions: list[str]           # required permission strings

    # Filtering
    filterable_fields: list[str]     # plain or "rel.field"
    filter_fns: dict[str, FilterFn]  # field -> custom fn (overrides built-in logic)
    default_filters: dict[str, Any]  # always-applied, not exposed as URL params

    # Sorting
    sortable_fields: list[str]       # plain or "rel.field"

    # Search
    search_fields: list[str]         # fields for ?q= ILIKE search; supports "rel.field" dot-notation
    search_fn: SearchFn | None       # custom search fn (overrides search_fields)

    # Hooks
    before_query: HookFn | None      # (query, request, current_user) -> query
    after_query: AfterFn | None      # (rows, request, current_user) -> rows

    # FastAPI
    dependencies: list[Any]          # extra Depends() to attach to the route
    tags: list[str]
```

At most one of `label_field` or `label_fn` may be set. When neither is provided, `label_field` defaults to `"name"`. Setting both raises a `CruditConfigError` at registration time.

---

## `options_endpoint()` signature

```python
def options_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    config: OptionsConfig,
    *,
    login_dep: Callable | None = None,       # FastAPI dependency returning current_user
    permission_dep: Callable | None = None,  # plain async callable, wrapped with Depends()
    summary: str | None = None,
    schema: type[BaseModel] = _DefaultOptionSchema,  # for join resolution only; defaults to {name: str}
    get_db: Callable,                                # FastAPI dependency returning AsyncSession
) -> None:
```

`schema` is used only for join resolution (same mechanism as `list_endpoint`), not for serialisation. It defaults to a minimal schema with a `name: str` field — pass an explicit schema when `label_fn` or filter/sort fields access related objects. The endpoint always returns `OffsetPaginatedResponse[OptionItem]` (no `page` or `itemsPerPage`).

**Usage example:**

```python
from crudit import options_endpoint, OptionsConfig

options_endpoint(
    router=router,
    path="/cities/{city_id}/districts/options",
    model=District,
    config=OptionsConfig(
        path_filters={"city_id": "city_id"},
        login_required=False,
        # Simple column label:
        label_field="name",
        # — or — computed label using related data:
        # label_fn=lambda row: f"{row.city.name} — {row.name}",
        sortable_fields=["name"],
        search_fields=["name"],
        filterable_fields=["is_active"],
    ),
    login_dep=get_current_user,
    schema=DistrictSchema,  # needed when label_fn uses row.city
    get_db=get_db,
)
```

```
GET /cities/1/districts/options?q=mont&sort=name&offset=0&limit=
→ {"data": [{"id": 1, "label": "Montmartre"}], "totalCount": 1, "hasMore": false}
```

---

## `ListConfig` reference

```python
@dataclass
class ListConfig:
    # Path parameters
    path_filters: dict[str, str]        # {"url_param": "model_field"}

    # Auth
    login_required: bool                # default True — 401 if no user
    permissions: list[str]              # required permission strings

    # Filtering
    filterable_fields: list[str]        # plain or "rel.field"
    filter_fns: dict[str, FilterFn]     # field -> custom fn (overrides built-in logic)
    default_filters: dict[str, Any]     # always-applied, not exposed as URL params

    # Sorting
    sortable_fields: list[str]          # plain or "rel.field"

    # Search
    search_fields: list[str]            # fields for ?q= ILIKE search; supports "rel.field" dot-notation
    search_fn: SearchFn | None          # custom search fn (overrides search_fields)

    # Hooks
    before_query: HookFn | None         # (query, request, current_user) -> query
    after_query: AfterFn | None         # (rows, request, current_user) -> rows

    # FastAPI
    dependencies: list[Any]             # extra Depends() to attach to the route
    tags: list[str]
```

---

## `ReadConfig` reference

```python
@dataclass
class ReadConfig:
    # Auth
    login_required: bool                # default True — 401 if no user
    permissions: list[str]              # required permission strings

    # Hooks
    before_query: HookFn | None         # (query, request, current_user) -> query
    after_query: ReadAfterFn | None     # (row, request, current_user) -> row

    # FastAPI
    dependencies: list[Any]             # extra Depends() to attach to the route
    tags: list[str]
```

---

## `CreateConfig` reference

```python
@dataclass
class CreateConfig:
    # Parent resolution
    parent_params: list[ParentParam]     # see ParentParam below

    # Auto-complete field setters
    field_setters: dict[str, FieldSetterFn]  # field -> (obj, request, user) -> value

    # Auth
    login_required: bool                 # default True — 401 if no user
    permissions: list[str]               # required permission strings

    # Hooks
    before_create: CreateHookFn | None   # (obj, request, current_user) -> obj
    after_create: CreateHookFn | None    # (obj, request, current_user) -> obj

    # FastAPI
    dependencies: list[Any]              # extra Depends() to attach to the route
    tags: list[str]
```

```python
@dataclass
class ParentParam:
    url_param: str               # path parameter name, e.g. "city_id"
    model: type[DeclarativeBase] # parent SQLAlchemy model to fetch
    child_field: str             # FK field to set on the new object, e.g. "city_id"
```

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
    login_dep: Callable | None = None,       # FastAPI dependency returning current_user
    permission_dep: Callable | None = None,  # plain async callable, wrapped with Depends()
    summary: str | None = None,
    get_db: Callable,           # FastAPI dependency returning AsyncSession
) -> None:
```

---

## `read_endpoint()` signature

```python
def read_endpoint(
    router: APIRouter,
    path: str,                  # must contain {id}
    model: type[DeclarativeBase],
    schema: type[BaseModel],
    config: ReadConfig,
    *,
    login_dep: Callable | None = None,       # FastAPI dependency returning current_user
    permission_dep: Callable | None = None,  # plain async callable, wrapped with Depends()
    summary: str | None = None,
    get_db: Callable,           # FastAPI dependency returning AsyncSession
) -> None:
```

The path must contain `{id}`. The primary key column is auto-detected from the SQLAlchemy mapper (composite primary keys are not supported). Join resolution runs at **registration time** (once), not per request.

---

## `create_endpoint()` signature

```python
def create_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    create_schema: type[BaseModel],  # input body schema
    read_schema: type[BaseModel],    # response schema (may include joined relations)
    config: CreateConfig,
    *,
    login_dep: Callable | None = None,       # FastAPI dependency returning current_user
    permission_dep: Callable | None = None,  # plain async callable, wrapped with Depends()
    summary: str | None = None,
    get_db: Callable,                # FastAPI dependency returning AsyncSession
) -> None:
```

Join resolution for `read_schema` runs at **registration time** (once). The primary key is auto-detected from the SQLAlchemy mapper. The `create_schema` is used for OpenAPI request body docs and Pydantic validation.

---

## `UpdateConfig` reference

```python
@dataclass
class UpdateConfig:
    # Auto-complete field setters
    field_setters: dict[str, FieldSetterFn]   # field -> (obj, request, user) -> value

    # Auth
    login_required: bool                      # default True — 401 if no user
    permissions: list[str]                    # required permission strings

    # Hooks
    before_update: UpdateBeforeHookFn | None  # (obj, patch_data, request, current_user) -> patch_data
    after_update: UpdateAfterHookFn | None    # (obj, request, current_user) -> obj

    # FastAPI
    dependencies: list[Any]                   # extra Depends() to attach to the route
    tags: list[str]
```

---

## `update_endpoint()` signature

```python
def update_endpoint(
    router: APIRouter,
    path: str,                   # must contain {id}
    model: type[DeclarativeBase],
    update_schema: type[BaseModel],  # partial input body schema (all fields typically optional)
    read_schema: type[BaseModel],    # response schema (may include joined relations)
    config: UpdateConfig,
    *,
    login_dep: Callable | None = None,       # FastAPI dependency returning current_user
    permission_dep: Callable | None = None,  # plain async callable, wrapped with Depends()
    summary: str | None = None,
    get_db: Callable,                # FastAPI dependency returning AsyncSession
) -> None:
```

The path must contain `{id}`. The primary key column is auto-detected from the SQLAlchemy mapper. Join resolution for `read_schema` runs at **registration time** (once). The `update_schema` is used for OpenAPI request body docs and Pydantic validation; fields not present in the request body are not applied to the object.

---

## `DeleteConfig` reference

```python
@dataclass
class DeleteConfig:
    # Auth
    login_required: bool                # default True — 401 if no user
    permissions: list[str]              # required permission strings

    # Hooks
    before_delete: DeleteHookFn | None  # (obj, request, current_user) -> None — raise to abort
    after_delete: DeleteHookFn | None   # (obj, request, current_user) -> None — obj is detached

    # FastAPI
    dependencies: list[Any]             # extra Depends() to attach to the route
    tags: list[str]
```

---

## `delete_endpoint()` signature

```python
def delete_endpoint(
    router: APIRouter,
    path: str,                  # must contain {id}
    model: type[DeclarativeBase],
    config: DeleteConfig,
    *,
    login_dep: Callable | None = None,       # FastAPI dependency returning current_user
    permission_dep: Callable | None = None,  # plain async callable, wrapped with Depends()
    summary: str | None = None,
    get_db: Callable,           # FastAPI dependency returning AsyncSession
) -> None:
```

The path must contain `{id}`. The primary key column is auto-detected from the SQLAlchemy mapper. No response schema is required — the endpoint always returns 204 No Content.

---

## `ReorderConfig` reference

```python
@dataclass
class ReorderConfig:
    # Path parameters
    path_filters: dict[str, str]         # {"url_param": "model_field"}

    # Auth
    login_required: bool                 # default True — 401 if no user
    permissions: list[str]               # required permission strings

    # Hooks
    before_reorder: ReorderHookFn | None  # (objects, request, current_user) -> None — raise to abort
    after_reorder: ReorderHookFn | None   # (objects, request, current_user) -> None — after commit

    # FastAPI
    dependencies: list[Any]              # extra Depends() to attach to the route
    tags: list[str]
```

---

## `reorder_endpoint()` signature

```python
def reorder_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],  # must have a sort_order column
    config: ReorderConfig,
    *,
    login_dep: Callable | None = None,       # FastAPI dependency returning current_user
    permission_dep: Callable | None = None,  # plain async callable, wrapped with Depends()
    summary: str | None = None,
    get_db: Callable,              # FastAPI dependency returning AsyncSession
) -> None:
```

The model must have a `sort_order` column — a `ValueError` is raised at registration time if it is absent. The primary key is auto-detected from the SQLAlchemy mapper. No response schema is required.

---

## Reorder endpoint response format

Reorder endpoints return an empty body with **HTTP 204 No Content**.

Status codes:
- **204** — positions updated successfully
- **401** — `login_required=True` and no authenticated user
- **403** — user authenticated but fails route-level or row-level permission check
- **404** — one or more IDs not found or outside the path-filtered scope
- **422** — request body failed schema validation

---

## Many-to-many router

`m2m_router` builds an `APIRouter` with three endpoints for managing a many-to-many relationship through an association table:

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/{prefix}/{parent_id}/{children}` | List children linked to a parent |
| `POST` | `/{prefix}/{parent_id}/{children}` | Add children by ID (idempotent) |
| `DELETE` | `/{prefix}/{parent_id}/{children}` | Remove children by ID (idempotent) |

### Setup

```python
from sqlalchemy import Column, ForeignKey, Integer, Table
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase): ...

user_permission = Table(
    "user_permission",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permissions.id"), primary_key=True),
)
```

```python
from fastapi import APIRouter
from crudit import m2m_router, M2MConfig
from pydantic import BaseModel

class PermissionSchema(BaseModel):
    id: int
    code: str

router = m2m_router(
    parent_model=User,
    child_model=Permission,
    association_table=user_permission,
    child_schema=PermissionSchema,
    prefix="/users",
    get_db=get_db,
    login_dep=get_current_user,
    config=M2MConfig(login_required=True),
)

app.include_router(router)
```

This registers:

```
GET    /users/{user_id}/permissions
POST   /users/{user_id}/permissions   body: {"ids": [1, 2, 3]}
DELETE /users/{user_id}/permissions   body: {"ids": [2]}
```

The parent path parameter name and child path segment are inferred automatically:
- **Parent param**: taken from the FK column in the association table that references the parent model's table (e.g. `user_id`).
- **Child segment**: `{child_model.__name__.lower()}s` by default (e.g. `permissions`). Override with `M2MConfig(child_path_segment="perms")`.

### Request / response

**GET** — returns a JSON array of `child_schema` objects.

**POST** — body: `{"ids": [1, 2, 3]}`. Returns the updated list. Raises **422** if any ID does not exist in the child table. Adding already-linked IDs is a no-op (idempotent).

**DELETE** — body: `{"ids": [2]}`. Returns **204 No Content**. Removing IDs that are not linked is a no-op (idempotent).

### `M2MConfig` reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `child_path_segment` | `str \| None` | `None` | URL segment for the child collection. Defaults to `{ChildModel.__name__.lower()}s`. |
| `tags` | `list[str]` | `[]` | OpenAPI tags for all three routes. |
| `dependencies` | `list[Any]` | `[]` | Extra FastAPI `Depends(...)` objects applied to every route. |
| `login_required` | `bool` | `True` | When `True`, the `login_dep` is enforced on every route. |
| `permissions` | `list[str]` | `[]` | Permission codes passed to `permission_dep`. |

### `m2m_router()` signature

```python
def m2m_router(
    *,
    parent_model: type,                          # SQLAlchemy ORM model (parent side)
    child_model: type,                           # SQLAlchemy ORM model (child side)
    association_table: Table,                    # SQLAlchemy association Table
    child_schema: type[BaseModel],               # Pydantic schema for child objects
    prefix: str,                                 # URL prefix, e.g. "/users"
    get_db: Callable,                            # FastAPI dependency returning AsyncSession
    config: M2MConfig | None = None,
    login_dep: Callable | None = None,           # FastAPI dependency returning current_user
    permission_dep: PermissionDepFn | None = None,
) -> APIRouter:
```

The returned `APIRouter` must be included in your FastAPI app with `app.include_router(router)`.

### Status codes

| Code | Meaning |
|------|---------|
| **200** | GET / POST — success |
| **204** | DELETE — success |
| **401** | `login_required=True` and `login_dep` raised 401 |
| **403** | Permission check failed |
| **404** | Parent not found |
| **422** | POST — one or more child IDs do not exist |
