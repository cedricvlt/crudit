# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in editable mode with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run a specific test file
pytest tests/list/test_endpoint.py

# Run a single test
pytest tests/list/test_endpoint.py::test_function_name -v
```

Tests use in-memory SQLite (`sqlite+aiosqlite:///:memory:`) and `pytest-asyncio` with `asyncio_mode = "auto"` — all test functions can be `async def` without any decorator.

## Architecture

**crudit** is a declarative CRUD endpoint factory for FastAPI + async SQLAlchemy 2.0. Each call to `list_endpoint(...)`, `read_endpoint(...)`, etc. registers a route on a FastAPI `APIRouter` at call time.

### Package layout

```
crudit/
  {verb}/
    config.py     # @dataclass config (ListConfig, ReadConfig, etc.)
    endpoint.py   # *_endpoint() registration function
  joins.py        # join resolution — runs once at registration time
  permissions.py  # row-level permission helpers (tenant_id / allowed_users)
  schemas.py      # shared response types: PaginatedResponse, OptionItem
  types.py        # Callable type aliases for hook signatures
  utils.py        # call_hook() — detects sync/async and awaits accordingly
  exceptions.py   # CruditConfigError, CruditForbidden
```

### Key architectural decisions

**Join resolution at registration time, not per-request.** `joins.py:resolve_joins()` inspects the Pydantic schema once when `*_endpoint()` is called. Any field annotated with a `BaseModel` subclass is matched to a SQLAlchemy relationship — `BaseModel` → `joinedload`, `list[BaseModel]` → `selectinload`. The resulting `JoinInfo` is captured in the route closure.

**Dot-notation for nested fields.** `filterable_fields=["city.name"]` or `sortable_fields=["city.name"]` triggers an explicit SQL `JOIN` on that relationship and switches from `joinedload` to `contains_eager`. This is resolved per-request by `collect_needed_joins()` in `joins.py`.

**Row-level permissions** are auto-detected from model attributes: if the model has `tenant_id`, the query is scoped to `current_user.tenant_id`; if it has `allowed_users`, a subquery filter is applied. Both conditions combine with OR. For `list_endpoint` this is a SQL WHERE clause; for `read_endpoint` it is a Python check that returns 403 (not 404).

**Hooks are sync/async transparent.** `utils.py:call_hook()` uses `inspect.iscoroutinefunction` to decide whether to `await` a hook, so all hook callables may be either sync or async.

**`_order_fields` convention.** Models should define `_order_fields = ("col",)` as a class attribute. This is used as the default ORDER BY when no `?sort=` parameter is sent.

### Test fixture structure

`tests/conftest.py` defines shared ORM models (`Tenant`, `User`, `City`, `District`) and fixtures (`engine` session-scoped, `db_session` function-scoped with rollback, `seed` which inserts and cleans up rows). Each endpoint subdirectory (`tests/list/`, `tests/create/`, etc.) has its own `conftest.py` and test files.

## Good practices

1. After you finished an implementation :
  - Run ruff linter on each modified file
  - Make sure the new code is commented and tested, and that the tests pass
  - Add the new feature in the README.md docs
