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
    path_filters={"city_id": "city_id"},   # filter District.city_id == path city_id
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
    # If you don't need the parent existence/permission check, pass
    # path_filters={"city_id": "city_id"} instead of parent_params and
    # drop the city_id field from DistrictCreateSchema.
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
        login_required=True,
        permissions=["erp:district:edit"],
        tags=["Districts"],
    ),
    path_filters={"city_id": "city_id"},
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
    option_schema=DistrictSchema,          # GET  /options  (response model + join resolution; must expose `label`)

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

No `OptionsConfig` is needed. Pass an explicit `options=OptionsConfig(...)` to add filtering, sorting, search, hooks, or auth.

By default the options endpoint returns `{id, label}` items with the label read from the model's `name` column. Pass `option_schema=MySchema` to control serialisation: the schema becomes the response model and drives join resolution (its nested relationship fields are eager-loaded). The schema must expose `id` and a `label` field — either a plain field (e.g. `label: str = Field(validation_alias="name")`) or a `@computed_field`. If the model has no `name` column, `option_schema` is required.

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

`login_dep`, `permission_dep`, `tags`, and `path_filters` are declared at the `crud_router` level because they are always the same for every endpoint on a given router:

| Argument | Type | Default | Description |
|---|---|---|---|
| `login_dep` | `Callable \| None` | `None` | FastAPI dependency returning `current_user` |
| `permission_dep` | `Callable \| None` | `None` | Plain async callable — wrapped with `Depends()` for route-level permission check |
| `tags` | `list[str] \| None` | `None` | OpenAPI tags applied to all registered routes |
| `path_filters` | `dict[str, str] \| None` | `None` | URL path param → model field. Forwarded to list, options, reorder, and create endpoints. |

### Nested resources via `path_filters`

For a nested resource like `/cities/{city_id}/districts`, pass `path_filters` once on `crud_router`:

```python
router = crud_router(
    model=District,
    list_item_schema=DistrictSchema,
    read_schema=DistrictSchema,
    create_schema=DistrictCreateSchema,
    update_schema=DistrictUpdateSchema,
    get_db=get_db,
    path_filters={"city_id": "city_id"},
    extra_endpoints=["options", "reorder"],
    shared=SharedConfig(login_required=False),
)

app.include_router(router, prefix="/cities/{city_id}/districts")
```

Behaviour per verb:
- **list / options**: adds `WHERE city_id = :city_id` to the query.
- **reorder**: any ID outside the URL scope is treated as not found (404).
- **create**: drops `city_id` from the request body schema and auto-injects the URL value before the row is persisted.
- **read / update / delete**: not affected — those verbs identify the row by its own `{id}` and apply row-level permissions instead.

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
| options | — | `option_schema` if provided, else `{id, label}` with the label from the model's `name` column |
| reorder | `{ids: [...]}` | — (204) |

### Notes

- `options` returns `{id, label}` (label from the model's `name` column) when no `option_schema` is provided. Pass `option_schema=MySchema` with a `label` field (plain or `@computed_field`) to customise.
- `reorder` requires the model to have a `sort_order` column.
- Paths are always relative to the router prefix set in `app.include_router(..., prefix=...)`.

### OpenAPI `operation_id`

Every endpoint registers a stable, predictable `operation_id` derived from the verb and the model class name in `snake_case`. The default scheme is:

| Verb | Default `operation_id` |
|---|---|
| list | `list_<model>` |
| read | `read_<model>` |
| create | `create_<model>` |
| update | `update_<model>` |
| delete | `delete_<model>` |
| options | `list_<model>_options` |
| reorder | `reorder_<model>` |
| m2m list / add / remove | `list_<parent>_<child>` / `add_<parent>_<child>` / `remove_<parent>_<child>` |

So for `class CompanyUser(...)` the list endpoint gets `list_company_user`. This makes generated client SDKs (e.g. `openapi-typescript-codegen`, `openapi-generator`) emit nice, deterministic method names instead of the long auto-generated FastAPI defaults.

Override the default in two ways:

```python
# 1. via the per-endpoint kwarg (highest priority)
list_endpoint(
    router, "/items", Item, ItemSchema, ListConfig(),
    operation_id="search_items",
    get_db=get_db,
)

# 2. via the per-verb Config
list_endpoint(
    router, "/items", Item, ItemSchema,
    ListConfig(operation_id="search_items"),
    get_db=get_db,
)
```

The `operation_id` keyword wins over the value declared on the config; both win over the auto-generated default. For `m2m_router`, set `M2MConfig.list_operation_id`, `add_operation_id`, and `remove_operation_id` to override per sub-endpoint.

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
| `created_by_id` | column exists and user is authenticated | `current_user.id` |

If the model also defines a `created_by` relationship, the response reloads it eagerly so it is never `null` when `created_by_id` was set.

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
7. Auto-fill `created_by_id` (if applicable)
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
    updated_by_id: int | None = None
```

### Auto-complete fields

| Field | Condition | Value |
|---|---|---|
| `updated_at` | column exists and has no `server_default` | `datetime.now(timezone.utc)` |
| `updated_by_id` | column exists and user is authenticated | `current_user.id` |

If the model also defines an `updated_by` relationship, the response reloads it eagerly so it is never `null` when `updated_by_id` was set.

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
6. Auto-fill `updated_by_id` into `patch_data` (if applicable)
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

Use the `path_filters` keyword argument to scope the reorder to a nested
collection. The same parameter is accepted by `list_endpoint`,
`options_endpoint`, `create_endpoint`, `reorder_endpoint`, and `crud_router`:

```python
reorder_endpoint(
    router=router,
    path="/cities/{city_id}/districts/reorder",
    model=District,
    config=ReorderConfig(...),
    path_filters={"city_id": "city_id"},  # WHERE city_id = :city_id
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
- **422** — request body failed schema validation, or unique constraint violation (see [Unique constraints](#unique-constraints))

---

## Update endpoint response format

Update endpoints return the updated object serialised as `read_schema`, with all joined relationships loaded:

```json
{ "id": 1, "name": "Renamed", "is_active": true, "city_id": 1, "city": { "id": 1, "name": "Paris" }, "updated_at": "2026-04-26T10:00:00Z", "updated_by_id": 1 }
```

Status codes:
- **200** — object updated successfully
- **401** — `login_required=True` and no authenticated user
- **403** — user authenticated but fails route-level or row-level permission check
- **404** — no object with that primary key exists
- **422** — request body failed schema validation, or unique constraint violation (see [Unique constraints](#unique-constraints))

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

Columns backed by a string-based SQLAlchemy `TypeDecorator` — such as sqlalchemy_utils' `PhoneNumberType` — are compared as plain text. Such types parse every bound value (e.g. into a `PhoneNumber`), which would otherwise make a filter or search string like `%555%` raise a parse error; crudit casts the column to `String` so filtering and search operate on the stored text instead.

All filter params — including operator-suffixed variants — are fully typed in the OpenAPI schema based on the SQLAlchemy column type. For example, `age__gte` is documented as `integer`, `created_at__lte` as `date`, and `name__isnull` as `boolean`. This means Swagger UI and generated clients show the correct input types with no extra configuration.

### OpenAPI error responses

Each endpoint declares the error responses it can return so they show up in Swagger UI and generated clients:

| Endpoint | Error responses |
|---|---|
| list / options | 403 (+ 401 if `login_dep` is set) |
| read / update / delete / create | 400, 403, 404 (+ 401 if `login_dep` is set), 422 for create/update body validation |
| reorder | 403, 404 (+ 401 if `login_dep` is set) |
| m2m list / add / remove | 403, 404, 422 on add (+ 401 when both `login_required=True` and `login_dep` is set) |

`401` is added automatically whenever `login_dep` is provided, since the dependency itself can raise `HTTPException(401)` regardless of the per-route `login_required` flag.

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

Detection **recurses into nested schemas**, so a chain like `District → City → Country` is loaded with a single chained `joinedload(District.city).joinedload(City.country)` — no manual eager-loading config needed.

Nested fields (e.g. `city.name`) in `filterable_fields`, `sortable_fields` or `search_fields` trigger an explicit `JOIN` on the related table and switch to `contains_eager` for that relationship. Multi-level paths like `city.country.name` are supported too — every prefix on the chain is JOINed in order and `contains_eager` is chained accordingly. For `sortable_fields` and `search_fields`, every intermediate segment must be a m2o relationship (joining through an o2m would multiply rows); a path that crosses a `list[…]` field is rejected with a `ValueError`.

### Filtering through collections (o2m / m2m)

`filterable_fields` additionally accepts paths that traverse a **collection** relationship — one-to-many or many-to-many. Instead of a `JOIN` (which would multiply rows and break pagination counts), crudit builds an `EXISTS` subquery via SQLAlchemy's `.any()` / `.has()`, so the match means *"the row has at least one related record matching the criterion"*:

```python
ListConfig(
    filterable_fields=[
        "inhabitants.id",            # District.inhabitants is a m2m / o2m
        "inhabitants.name",
        "inhabitants.company.name",  # collection → m2o nesting also works
    ],
)
```

```
GET /districts?inhabitants.id__in=1,2,3      # districts having any inhabitant 1, 2, or 3
GET /districts?inhabitants.name__ilike=%al%
GET /districts?inhabitants.company.name=Acme
```

Unlike m2o paths, a filtered collection relationship does **not** need to be declared on the response schema — it is resolved straight from the SQLAlchemy mapper, so you can filter by `inhabitants` without embedding the inhabitants list in every response. All standard operators apply to the leaf column (`__in`, `__ilike`, `__gte`, …). Sorting and search through a collection remain unsupported.

### `@property` fields

Schemas can include fields that map to a plain Python `@property` on the model (instead of a `mapped_column` or `relationship`). crudit detects these at registration time, **excludes them from the SQL query**, and lets Pydantic evaluate them per row via `from_attributes=True`. Properties returning either scalar values or nested `BaseModel`-shaped objects are both supported.

Because properties have no SQL form, they cannot appear in `filterable_fields`, `sortable_fields`, or `search_fields` — doing so raises `CruditConfigError` at registration. SQLAlchemy `hybrid_property` (which does have a SQL expression form) is **not** affected and keeps working in queries.

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

## Unique constraints

`create_endpoint` and `update_endpoint` automatically detect unique constraints declared on the SQLAlchemy model and validate every write against them. **No configuration is required** — the model is the source of truth.

Three definition styles are recognised:

```python
class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (
        # 2. Composite UniqueConstraint
        UniqueConstraint("city_id", "name", name="uq_tag_city_name"),
        # 3. Unique Index
        Index("ix_tag_code_unique", "code", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # 1. Column-level unique=True
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
```

A pre-flight `SELECT` runs before the row is persisted; if a conflict is detected, the request fails with **422 Unprocessable Entity** and a structured detail naming the offending fields:

```json
{
  "detail": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed",
    "fields": {
      "city_id": ["Already exists"],
      "name": ["Already exists"]
    }
  }
}
```

For `update_endpoint`, the row being updated is excluded from the check so a no-op PATCH (re-sending a row's existing values) doesn't false-positive against itself. The check uses the *post-patch* values.

**NULL semantics.** If any column in a unique spec has the value `None`, that spec is skipped — matching SQL's rule that NULLs do not conflict with each other.

**Race-safety.** The `commit()` is also wrapped with an `IntegrityError` catch, so a concurrent insert that sneaks past the pre-flight still surfaces as 422 (rather than 500).

---

## Foreign key validation

`create_endpoint` and `update_endpoint` automatically validate every foreign-key column declared on the SQLAlchemy model before persisting. **No configuration is required** — the model is the source of truth.

A single pre-flight SQL query checks every relevant FK in one round-trip (one labeled scalar subquery per FK). If any reference is missing, the request fails with **422 Unprocessable Entity** naming every offending column:

```json
{
  "detail": {
    "code": "VALIDATION_ERROR",
    "message": "Validation failed",
    "fields": {
      "city_id": ["Does not exist"],
      "company_id": ["Does not exist"]
    }
  }
}
```

**Scope.**
- *`create_endpoint`*: only FKs that appear in the request body are checked. FKs set from `parent_params` are skipped (they're already 404-validated upstream), FKs set from `path_filters` are skipped (URL-derived), and the auto-set `created_by_id`/`updated_by_id` columns are skipped (trusted from `current_user.id`).
- *`update_endpoint`*: only FKs included in the PATCH body are checked. A PATCH that doesn't mention any FK column issues zero FK queries. The auto-set `updated_by_id` is skipped. The FK check runs before the unique-constraint check, so an invalid FK is reported instead of a downstream uniqueness error.

**NULL bypass.** A `None` value for a nullable FK is skipped — there is nothing to look up.

**Race-safety.** The `commit()` is wrapped with an `IntegrityError` catch, so a target row deleted between pre-flight and commit still surfaces as 422 (rather than 500).

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
from crudit import CruditContext

async def log_query(query: Select, ctx: CruditContext) -> Select:
    logger.info("list query by %s", ctx.user.id)
    return query

def redact_sensitive(rows: list, ctx: CruditContext) -> list:
    if not ctx.user.is_admin:
        for row in rows:
            row.secret = None
    return rows

config = ListConfig(
    before_query=log_query,   # (query, ctx) -> query
    after_query=redact_sensitive,  # (rows, ctx) -> rows
)
```

The same hooks apply to `OptionsConfig`. `after_query` receives ORM model instances — after the hook the endpoint serialises them with the response schema.

### Read endpoint hooks

```python
async def log_read(query: Select, ctx: CruditContext) -> Select:
    logger.info("read query by %s", ctx.user.id)
    return query

def redact_single(row, ctx: CruditContext):
    if not ctx.user.is_admin:
        row.secret = None
    return row

config = ReadConfig(
    before_query=log_read,    # (query, ctx) -> query
    after_query=redact_single,  # (row, ctx) -> row
)
```

`before_query` runs before the database call. `after_query` receives the ORM object after the permission check passes, before serialization.

### Computed fields

`list_endpoint` and `read_endpoint` support adding **SQL-level computed fields** to the response — typically aggregates such as counting rows in a one-to-many relationship. The expression is injected as a labeled column on the main `SELECT`, so the value is computed in a single round-trip without loading the underlying collection.

Each entry maps a field name to a callable that receives the model class and returns a SQL scalar expression (usually a correlated subquery). The response schema must declare the field.

```python
from sqlalchemy import func, select
from crudit import ListConfig

class UserSchema(BaseModel):
    id: int
    name: str
    post_count: int

config = ListConfig(
    computed_fields={
        "post_count": lambda User: (
            select(func.count(Post.id))
            .where(Post.user_id == User.id)
            .correlate(User)
            .scalar_subquery()
        ),
    },
)
```

The same option exists on `ReadConfig`. Crudit validates at registration time that each computed field name is declared on the response schema and does not collide with a column on the model.

Computed field names are automatically added to `sortable_fields` on `list_endpoint`, so `?sort=post_count` and `?sort=-post_count` work out of the box. To filter on a computed field, add it to `filterable_fields` explicitly; all standard operators are supported (`?post_count__gte=5`, `?post_count=0`, etc.). Searching on computed fields is not supported.

### `CruditContext`

Hooks for `list_endpoint`, `options_endpoint`, and `read_endpoint` receive a `CruditContext` instead of the FastAPI `Request`. This lets the same business logic run from non-HTTP callers (MCP tools, background jobs, CLIs):

```python
@dataclass
class CruditContext:
    user: Any                          # current user (or None)
    path_params: dict[str, Any]        # from request.path_params or supplied directly
    query_params: dict[str, str]       # from request.query_params or supplied directly
    request: Request | None            # underlying Starlette request (None off-HTTP)
    extras: dict[str, Any]             # caller-supplied scratch space
```

Create, update, delete, and reorder hooks still receive `(obj, request, current_user)` for now.

---

## Calling endpoints as services

Each endpoint module exposes a pure async **service** function that the FastAPI handler delegates to. The service has no `Request` / `Depends` coupling, so it can be called directly from MCP tools, scheduled jobs, or tests:

```python
from crudit import CruditContext, ListConfig, list_service, read_service, CruditNotFound

# List
ctx = CruditContext(user=current_user, path_params={"city_id": 1})
result = await list_service(
    db,
    ctx,
    model=District,
    schema=DistrictSchema,
    config=ListConfig(filterable_fields=["name"]),
    path_filters={"city_id": "city_id"},
    q="mont",
    sort="name",
    page=1,
    items_per_page=20,
    filter_params={"name": ["mont"]},  # same shape as extract_filter_params(...)
)
# result is a PaginatedResponse[DistrictSchema]; or an int when count_only=True

# Read
try:
    obj = await read_service(
        db, ctx,
        model=District, schema=DistrictSchema,
        config=ReadConfig(login_required=True),
        id=42,
    )
except CruditNotFound:
    ...
```

Services raise domain exceptions (`CruditNotFound`, `CruditForbidden`, `CruditValidationError`) instead of `HTTPException`. The endpoint layer is the only place that translates them to HTTP status codes.

---

## Default sort

Every model should declare `_order_fields` as a tuple of column names. This is used when the client sends no `?sort=` parameter:

```python
class District(Base):
    ...
    _order_fields = ("name",)  # always sort by name ASC when no sort param given
```

Sort columns always use `NULLS LAST`.

### Schema fields are sortable by default

For `list_endpoint` and `options_endpoint`, every SQL-backed field of the response schema — including nested ones reached through m2o relationships — is automatically added to `sortable_fields`. Anything passed in `config.sortable_fields` is **extra**, on top of these defaults.

Skipped from auto-defaulting: `@property` attributes (no SQL form), `hybrid_property` (must be opted in explicitly), and o2m nested fields like `list[BaseModel]` (joining through a collection would multiply rows).

```python
class DistrictSchema(BaseModel):
    id: int
    name: str
    is_active: bool
    city: CitySchema   # nested m2o

list_endpoint(..., schema=DistrictSchema, config=ListConfig())
# ?sort=name, ?sort=-is_active, ?sort=city.name all work — no explicit list needed.
```

`filterable_fields` and `search_fields` keep their explicit, opt-in behaviour.

---

## `OptionsConfig` reference

```python
@dataclass
class OptionsConfig:
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

The `label` is supplied by the response schema, not by `OptionsConfig` (see `options_endpoint()` below).

---

## `options_endpoint()` signature

```python
def options_endpoint(
    router: APIRouter,
    path: str,
    model: type[DeclarativeBase],
    config: OptionsConfig,
    *,
    path_filters: dict[str, str] | None = None,  # {"url_param": "model_field"}
    login_dep: Callable | None = None,       # FastAPI dependency returning current_user
    permission_dep: Callable | None = None,  # plain async callable, wrapped with Depends()
    summary: str | None = None,
    schema: type[BaseModel] | None = None,  # response model + join resolution; must expose `label`
    get_db: Callable,                       # FastAPI dependency returning AsyncSession
) -> None:
```

Rows are serialised with `schema`, which must expose a `label` field. The schema also drives join resolution (same mechanism as `list_endpoint`), so any nested relationship fields it declares are eager-loaded. The response is `OffsetPaginatedResponse[schema]` (no `page` or `itemsPerPage`).

When `schema` is omitted, items are shaped as `{id, label}` with the label read from the model's `name` column. If the model has no `name` column, an explicit `schema` is required (otherwise `options_endpoint` raises `CruditConfigError` at registration time). `crud_router` wires its `option_schema` argument straight to this parameter.

The `label` can be a plain field (mapped from a column via `validation_alias`) or a `@computed_field` built from other declared fields:

```python
from pydantic import BaseModel, Field, computed_field

# Plain field via alias — subclassing OptionItem is fine in this form:
class DistrictOption(BaseModel):
    id: int
    label: str = Field(validation_alias="name")

# Computed label — subclass BaseModel, NOT OptionItem: Pydantic forbids
# overriding the inherited `label` field with a computed field. Feed the
# label from excluded fields so the output stays {id, label}; declaring
# `city` also triggers the join automatically.
class DistrictOption(BaseModel):
    id: int
    name: str = Field(exclude=True)
    city: CitySchema = Field(exclude=True)

    @computed_field
    @property
    def label(self) -> str:
        return f"{self.city.name} — {self.name}"
```

**Usage example:**

```python
from crudit import options_endpoint, OptionsConfig

options_endpoint(
    router=router,
    path="/cities/{city_id}/districts/options",
    model=District,
    config=OptionsConfig(
        login_required=False,
        sortable_fields=["name"],
        search_fields=["name"],
        filterable_fields=["is_active"],
    ),
    path_filters={"city_id": "city_id"},
    login_dep=get_current_user,
    # schema omitted → {id, label} from the model's `name` column.
    # Pass schema=DistrictOption to build the label from related data.
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

    # Computed fields — SQL-level scalar expressions added to each row
    computed_fields: dict[str, Callable[[type[Model]], Any]]

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

    # Computed fields — SQL-level scalar expressions added to the row
    computed_fields: dict[str, Callable[[type[Model]], Any]]

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
    path_filters: dict[str, str] | None = None,  # {"url_param": "model_field"}
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
    path_filters: dict[str, str] | None = None,  # {"url_param": "model_field"}
    login_dep: Callable | None = None,       # FastAPI dependency returning current_user
    permission_dep: Callable | None = None,  # plain async callable, wrapped with Depends()
    summary: str | None = None,
    get_db: Callable,                # FastAPI dependency returning AsyncSession
) -> None:
```

Join resolution for `read_schema` runs at **registration time** (once). The primary key is auto-detected from the SQLAlchemy mapper. The `create_schema` is used for OpenAPI request body docs and Pydantic validation.

When `path_filters` is set, each mapped field is **stripped from the request body schema** and auto-injected from the URL path before the row is persisted, so a nested resource can keep using a flat schema. Example: with `path="/cities/{city_id}/districts"`, `path_filters={"city_id": "city_id"}`, the body of `POST /cities/1/districts` is just `{"name": "Belleville"}` and `city_id=1` is set from the URL. Use `path_filters` when you only need scoping; use `parent_params` when you also need the parent's existence and row-level permissions checked.

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
    path_filters: dict[str, str] | None = None,  # {"url_param": "model_field"}
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

`child_schema` may declare nested relationship fields (e.g. `company: CompanySchema | None`). They are resolved with the same eager-loading logic as `read`/`list` endpoints, so nested objects are populated in both the GET response and the POST response without triggering lazy loads under the async session.

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
| `after_add` | `M2MHookFn \| None` | `None` | Called after links are inserted, before commit. See [Hooks](#hooks-5). |
| `after_remove` | `M2MHookFn \| None` | `None` | Called after links are deleted, before commit. See [Hooks](#hooks-5). |

### Hooks

`after_add` and `after_remove` run inside the same transaction as the link changes, **after** the `INSERT`/`DELETE` and **before** `db.commit()`. Both may be sync or async (crudit awaits accordingly). The signature is:

```python
def hook(parent_id: int, child_ids: list[int], session: AsyncSession, current_user: Any) -> Any: ...
```

- `parent_id` — the parent path-parameter value.
- `child_ids` — for `after_add`, only the ids **actually inserted** (already-linked ids are filtered out); for `after_remove`, the requested ids verbatim (the operation is idempotent, so they may not all have been linked).
- `session` — the endpoint's `AsyncSession`. Writes made through it are committed together with the link change.
- `current_user` — the value resolved by `login_dep`, or `None` when no `login_dep` is configured.

Because both hooks share the request transaction, raising from a hook rolls back the link change along with anything the hook wrote. The hooks fire only when there is real work to do: `after_add` is skipped when no new links are inserted (empty body or all ids already linked), and `after_remove` is skipped for an empty body.

```python
async def after_add(parent_id, child_ids, session, current_user):
    session.add(AuditLog(action="link", parent_id=parent_id, child_ids=child_ids))

config = M2MConfig(after_add=after_add)
```

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
