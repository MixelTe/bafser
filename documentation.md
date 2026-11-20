# bafser guide

This guide describes the implemented library API and application upgrade steps.
Supported Python starts at 3.10; dependency bounds are in `pyproject.toml`.

## Choosing a startup workflow

For a small application with one process, `AUTO_SETUP=True` allows startup to
prepare its configured database and files. This does not require Redis, a worker
service or a secret-management service.

For separately deployed web processes and background tasks, use
`AUTO_SETUP=False`. Run `--setup` once as part of deployment, then start the
runtime processes. `MULTIPROCESS_LOGGING` controls safe shared-file logging
independently of setup. `DEV_MODE` controls development behavior and diagnostics.

Importing `bafser` or asking the CLI for help does not scaffold a project or
create its database. Explicit generator/setup operations may create files.

## Quick start

Create and activate a Python environment, install the package, then:

```sh
bafser init_project
```

If no config exists, this creates `bafser_config.py` and asks you to edit it and
run the generator again. For a simple SQLite application, keep the generated
`db_dev_path` and set `use_alembic = False`. Rerun the command and finish the
generator's configuration prompt by answering `n` when the config is ready:

```sh
bafser init_project
python main.py dev
```

The generator preserves existing files. `--force` permits replacement;
`--directory PATH` selects a destination independently of the process cwd.
Review generated files before enabling a public endpoint.

The project contains a `UserBase` subclass in `data`, role and operation
definitions, blueprints and `main.py`. A minimal entry point has this shape:

```python
import sys

from bafser import AppConfig, create_app

app, run = create_app(
    __name__,
    AppConfig(
        DEV_MODE="dev" in sys.argv,
        AUTO_SETUP=True,
        JWT_COOKIE_SECURE="dev" not in sys.argv,
    ),
)

run(__name__ == "__main__", port=5000)
```

The development initializer runs only when the database is first initialized.
Restarting an initialized database does not reseed it. Production setup replaces
the well-known initial admin password; set your intended admin password through
the CLI before exposing the application.

### Application recipes

The main startup/logging choices are independent:

| Option | Default | Use |
| --- | --- | --- |
| `DEV_MODE` | `False` | Development server/debug behavior and full available diagnostics |
| `AUTO_SETUP` | `True` | Prepare keys/directories/schema and seed data for simple startup |
| `MULTIPROCESS_LOGGING` | `False` | Coordinate rotation when multiple processes write the same files |
| `CONFIGURE_ROOT_LOGGING` | `True` | Add bafser root handlers; False leaves general logging to the host |
| `LOG_ERROR_DETAILS` | `True` | Full server messages/exceptions; False reduces production diagnostics |
| `LOG_JSON_RESPONSES` | `DEV_MODE` | Permit response JSON diagnostics, subject to body policy |
| `REQUEST_POLICY` | Optional user JWT, no production body/query | Early limits and route diagnostics |
| `HEALTH_ROUTE` | `False` | Optional database health endpoint; True selects `/api/health` |

A local one-process prototype can use the quick-start entry point above. With
`use_alembic=False` in its config, this prepares SQLite and starts the development
server. Keep `JWT_COOKIE_SECURE=False` only for local HTTP development.

For production, use an importable `main.py` with explicit runtime settings:

```python
from pathlib import Path

from bafser import AppConfig, RequestPolicy, create_app

PROJECT_DIR = Path(__file__).resolve().parent
app, run = create_app(__name__, AppConfig(
    FRONTEND_FOLDER=str(PROJECT_DIR / "build"),
    AUTO_SETUP=False,
    MULTIPROCESS_LOGGING=True,
    REQUEST_POLICY=RequestPolicy(max_content_length=64 * 1024),
))
run(__name__ == "__main__")
```

`run(False)` still initializes the database runtime when a WSGI server imports
this module. It does not start Flask's server or prepare the schema with
`AUTO_SETUP=False`. To use host-owned general logging, also set
`CONFIGURE_ROOT_LOGGING=False`; bafser's named loggers remain configured.

A background command can import that same production app and own its Session:

```python
from sqlalchemy import text

from bafser import db_session
from main import app

with app.app_context(), db_session.create_session() as db_sess:
    with db_sess.begin():
        print(db_sess.execute(text("SELECT 1")).scalar_one())
        # Pass this Session and commit=False to composed model operations.
```

Run finite commands from the project's environment, for example
`/srv/myapp/venv/bin/python /srv/myapp/current/check_db.py`. Web and background
processes must select the same configuration, keys and persistent storage.

For deployment, build/install the application environment, select persistent
paths in `bafser_config.py`, then run once:

```sh
/srv/myapp/venv/bin/python /srv/myapp/current/main.py --setup
```

Start the prepared app through the hosting WSGI service. For a server configured
with Gunicorn, an example command is:

```sh
/srv/myapp/venv/bin/gunicorn --chdir /srv/myapp/current --workers 2 --bind 127.0.0.1:8000 main:app
```

Choose worker count and database pools for the actual resource limit. For hosting
that accepts a WSGI file, its callable can be `from main import app as application`;
configure the project's import path and Python environment in that service.
After an update, replace/reload all application workers with the server's supported
mechanism. Touching an arbitrary Python file does not guarantee a full reload.
Keep normal startup at `AUTO_SETUP=False`. Serialize setup, preserve signing keys,
apply compatible migrations before activation, or stop old writers for incompatible
ones, then perform an API/database smoke check.

Flask documents production WSGI deployment and the `module:app` Gunicorn entry point
in its [deployment guide](https://flask.palletsprojects.com/en/stable/deploying/gunicorn/).

## Configuration and paths

The project config is a Python module named `bafser_config`. Importable packages
and filesystem paths have separate meanings:

```python
blueprints_package = "blueprints"
data_tables_package = "data"
```

Use dotted names such as `myapp.http` and `myapp.models` for nested packages.
Set either setting to `None` to disable that project-specific discovery. The
library's built-in tables are still imported. The old `*_folder` keys are errors,
not aliases. A configured package or internal dependency that cannot be imported
causes a clear failure instead of silently skipping routes or models.
Disabling discovery is not a complete built-in authentication schema: database
setup still requires the application's concrete `UserBase` subclass for its user
table and related foreign keys. Code using only schemas/response helpers need not
initialize a database.

Discovery imports immediate child modules in deterministic order. Blueprint
modules export `bp` (`blueprint` remains supported); modules beginning with `_` are helpers, not
automatically registered endpoints. Model discovery includes `_roles`,
`_operations` and `_tables`. Child packages are responsible for their own internal
imports. Arbitrary recursive discovery and ORM module reload are not performed.

The project root must be available to normal Python imports. An absolute script
path, installed application package or explicit WSGI bootstrap can provide it.
Changing a path into an import name by replacing slashes is unsupported.

The installed `bafser` command prepares the project's import path before loading
its configuration, including imports of sibling settings modules. For
`bafser init_project --directory PATH`, the selected directory also supplies the
configuration and `.env`; an unrelated current directory is not its project.
Use the installed command for that bootstrap. `python -m bafser` first imports
the library, so an invalid configuration in its current directory can fail before
it processes `--directory`.

Anchor project-owned paths explicitly. For example, in a generated config:

```python
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent
load_dotenv(PROJECT_DIR / ".env", override=False)
STORAGE_DIR = PROJECT_DIR / "storage"

db_dev_path = str(STORAGE_DIR / "db" / "dev.db")
migrations_folder = str(PROJECT_DIR / "alembic")
images_folder = str(STORAGE_DIR / "images")
jwt_key_file_path = str(STORAGE_DIR / "secret_key_jwt.txt")
```

Likewise pass an absolute `FRONTEND_FOLDER` to `AppConfig` when startup can use a
different working directory; do not depend on cwd for static asset discovery.

Keep the other generated settings, including log paths, database mode and URL
prefixes. Production applications should select one absolute persistent storage
directory shared by their setup, WSGI and worker entry points.

The Telegram config template anchors `log_bot_path`, `config_path` and
`config_dev_path` to these directories as well. Its `bot_folder="bot"` keeps the
optional integration's legacy relative-directory/import-prefix contract: run that
integration from the project root, rather than replacing this value with an
absolute filesystem path.

The CLI loads `.env` from its working directory with `override=False`;
existing environment values take precedence. Parent `.env` files are not searched.
Application entry points load their own explicit `.env` when needed. Avoid running
the application against a different config/environment merely because cwd changed.

### MySQL credentials and pool settings

`db_path = "ENV:DBPATH"` obtains the connection description from the environment.
Alternatively, use the existing password-file mechanism:

```text
DB_PASSWORD_FILE=/private/database-password.txt
DB_USER=application_user
DB_HOST=database_host
DB_PORT=3306
DB_NAME=application_database
```

With this mechanism the password is read from a file, not concatenated into a URL
by the application. Do not expose credential values in errors or diagnostics.

Optional database settings have these defaults:

| Setting | Default | Meaning |
| --- | --- | --- |
| `db_pool_size` | `5` | Persistent pool capacity per process |
| `db_max_overflow` | `10` | Additional checked-out connections per process |
| `db_pool_timeout` | `30` | Seconds waiting for a pool connection |
| `db_pool_recycle` | `3600` | Maximum age before pooled connection recycling |
| `db_connect_timeout` | `10` | MySQL connection timeout, seconds |
| `db_read_timeout` | `30` | MySQL read timeout, seconds |
| `db_write_timeout` | `30` | MySQL write timeout, seconds |
| `db_hide_parameters` | `None` | Automatic hiding outside dev; explicit bool overrides |

Pool capacity is an upper bound, not an eager opening of all connections. The
account-wide bound grows with the number of processes and applications. Set limits
from measured workload and hosting limits. SQLite connection hooks affect only
their corresponding SQLite engine.

`db_session.global_init(dev, create_tables=False)` initializes the engine/factory.
Normal initialization does not create tables. Explicit setup may request
`create_tables=True` for a project without Alembic. `get_engine()` exposes the
initialized engine and `dispose_engine()` releases/reset its library-owned runtime
state. Close outstanding sessions before disposal. Creating a session before
initialization or reinitializing with incompatible settings is an error.

## JSON schemas and Undefined

Use `JsonObj` for a validated input schema:

```python
from bafser import JsonObj, JsonOpt, Undefined


class EditItem(JsonObj):
    name: JsonOpt[str] = Undefined
    note: JsonOpt[str | None] = Undefined
    quantity: JsonOpt[int] = JsonObj.field(min_value=1, max_value=100)

    def _validate_object(self) -> str | None:
        if self.name is not Undefined and not self.name.strip():
            return "name must not be blank"
        return None
```

`JsonObj.new(data)` parses but does not by itself guarantee validation:

```python
payload = EditItem.new({"note": None})
payload.valid()  # Raises JsonParseError for invalid data.
```

`validate()` returns an error string or `None`. `get_from_req()` parses and
validates an HTTP object; `get_list_from_req()` does the same for a list. Unknown
keys are rejected by default. `__allow_unknown_fields__ = True` is an explicit
schema-level exception, useful for separately validated external payloads.
`get_json_values*` are simpler extraction helpers; they do not promise the same
strict unknown-key policy.

Fields can have bounds, finite-number requirements, string/list lengths, a full
regular-expression pattern, choices and validators. Use `default_factory` for
mutable defaults. `_validate_object` checks relationships after field validation.
Keep response DTOs explicit; serializing an ORM object does not automatically make
every field safe for public clients.

### Missing, null and false are different

`Undefined` is the class sentinel itself. Never instantiate `Undefined()`.

| Annotation | Field may be omitted | Explicit JSON null |
| --- | --- | --- |
| `str` | No | No |
| `str | None` | No | Yes |
| `JsonOpt[str]` | Yes | No |
| `JsonOpt[str | None]` | Yes | Yes |

Use `= Undefined` when a direct-constructor argument should also be optional.
For a partial update:

```python
if Undefined.defined(payload.note):
    item.note = payload.note
```

An omitted note keeps the existing value; explicit `None` may clear it.
`Undefined.default(value, fallback)` substitutes only the sentinel, preserving
`None`, `False`, `0` and `""`. Truthiness checks and `value or fallback` do not
express this behavior. `Undefined.cast` only narrows a type; it does not validate
or convert the runtime value. `U` and `UD` are aliases for `Undefined` and its
`default` helper.

### Errors and dates

Raise `PublicError(message, status=..., code=..., details=...)` only with text and
details intended for the client. Unexpected errors remain a generic 500 response.
API errors use `msg` and optional `code`/`details`; standard HTTP errors preserve
their status and relevant headers, including `Allow` and `Retry-After`.

With `datetime_utc=True`, new API timestamps use UTC. `get_datetime_utc()` gives an
aware UTC instant. `parse_datetime` normalizes offset-bearing input to naive UTC
for database storage in that mode; `parse_date` keeps a calendar date without
shifting it to another day. Do not mix naive and aware values in comparisons or
silently change a legacy database's time convention during an upgrade.

## Models, sessions and transactions

`SqlAlchemyBase` provides the SQLAlchemy declarative/dataclass base. `IdMixin`
adds an integer ID; `ObjMixin` also adds soft deletion. Its query helpers exclude
deleted rows unless `includeDeleted=True` is supplied. `BigIdMixin` provides a
short display/lookup identifier, not an authorization secret.

```python
from sqlalchemy.orm import Mapped

from bafser import ObjMixin, SqlAlchemyBase


class Item(SqlAlchemyBase, ObjMixin):
    __tablename__ = "Item"
    name: Mapped[str]
```

Use the request session or provide one explicitly:

```python
item = Item.get(item_id)
item = Item.get(item_id, db_sess=session)
items = Item.all(db_sess=session)
```

Background code initializes runtime and owns a session:

```python
from bafser import db_session

db_session.global_init(dev=False)
with db_session.create_session() as session:
    with session.begin():
        item = Item.get(item_id, db_sess=session)
        if item is not None:
            item.name = "Updated"
```

Use an application context as well when code needs Flask config, images or other
application resources. A Session belongs to one concurrent operation/thread; do
not pass ORM instances or their session to another worker.

`use_db_sess` obtains the request session or creates/closes one. It does not commit
automatically. Prefer explicit sessions for composed operations and background
jobs. Override hooks for session/current-user lookup are application integration
points; they must preserve ownership and locking requirements.

### Commit contract

Public CRUD methods keep `commit=True` as their convenient default. For a composed
operation, pass one session and `commit=False` through the participating methods:

```python
from bafser import Log

with db_session.create_session() as session:
    with session.begin():
        item = Item.get(item_id, db_sess=session)
        if item is not None:
            item.name = "Updated"
            Log.updated(item, actor=None, db_sess=session, commit=False)
```

The outer transaction commits the whole operation or rolls it back. A nested
library call with `commit=False` does not secretly commit. It may flush to obtain
an ID: `flush` sends pending changes but does not commit them. A Session commit
persists every pending change in that Session, not only the object being logged.

Do not mechanically add `commit=False` without an outer owner that saves the
operation. `SingletonMixin.get` can create its initial row; select its commit
behavior when it participates in a larger operation. `Log.added` may flush the
session. Image creation can roll back its supplied session on failure, even with
`commit=False`; callers must treat that as failure of their composed operation.

### Row locks

```python
with db_session.create_session() as session:
    with session.begin():
        item = Item.get(item_id, db_sess=session, for_update=True)
        if item is not None:
            item.require_for_update()
            item.name = "Changed under the lock"
```

`for_update=True` acquires the lock and refreshes the selected object. Constructing
the query alone does not. `is_for_update` is a read-only mark for the current
session/transaction; `require_for_update()` checks it without acquiring a lock.
Commit, rollback, close or detachment invalidates the mark. A SAVEPOINT rollback
conservatively invalidates marks; releasing it preserves them.

Only explicitly selected objects from tracked helper queries are marked.
Relationships and arbitrary SQLAlchemy queries do not inherit that mark. Tracked
results are buffered; use bounded queries, not unbounded streaming. Keep the
exclusive FOR UPDATE clause unmodified. Normal autoflush may write pending
changes before the locking SELECT; disabling autoflush can cause a refresh to
discard pending edits.

SQLite can emulate the protocol when `allow_unsupported_for_update_clause=True`.
That does not provide a real row lock. Real concurrency must be tested on the
production database engine. Under snapshot isolation, locking one row does not
refresh unrelated values loaded earlier through ordinary queries.

### Audit authors

```python
Log.updated(item)                  # Current user, otherwise the system.
Log.updated(item, actor=operator)  # Explicit user.
Log.updated(item, actor=None)      # Explicit system action.
```

The default `actor=Undefined` means automatic selection. A system audit entry has
`userId=None`, not the ID of a fabricated admin, and keeps a system label.
Financial/background code passes its actual session. Audit fields hidden through
`__fields_hidden_in_log__` are excluded from ordinary change capture. Explicit
audit changes must also avoid secrets.

`Role.update_roles_permissions(session, commit=False)` synchronizes loaded
permission collections immediately and remains repeatable before the outer
commit. It explicitly flushes the whole Session even inside `no_autoflush`, then
expires only affected permission collections. It does not commit the outer work.

### Files and images

`Image.new` accepts bounded base64 PNG/JPEG/GIF data and verifies its declared type
against magic bytes. This is not a complete image decoder or pixel-count check.
Applications that render/process images must validate those resources at that
boundary.

Created files follow the database transaction: rollback/close removes uncommitted
files; successful commit preserves them. An ambiguous COMMIT is checked using a
fresh transaction. If its outcome cannot be established, retain the file for
reconciliation. This avoids deleting a file whose database row may be committed.
Keep the session/transaction ownership documented by `track_created_file`.

File-recovery diagnostics retain the event, file/row reference, full path and
exception by default.
With `LOG_ERROR_DETAILS=False` in production, they retain a constant event, safe
numeric row reference and opaque file reference instead. In this reduced mode,
the source log record also omits raw paths and exception values, including when
a host uses an ordinary formatter.
To match a candidate file, reproduce the reference from the exact tracked path:
`hashlib.sha256(path.encode("utf8", "surrogatepass")).hexdigest()[:24]`.
Use the same path spelling, including whether it is absolute. Paths longer than
32768 characters and unsupported row identities are omitted from these references;
the full path is still logged when error details are enabled.
Development always retains the full path and exception.

`create_file_response` and image file responses default to `private, no-store`.
Public caching must be intentional. The helper does not provide file permissions
or entity-level authorization: the route checks those before sending the file.

### Normalized search columns

`normalized_column(source, normalizer=...)` stores a derived search field. Use
concrete ORM source attributes; the helper synchronizes assignment and flushes.
`normalize_search` supports Unicode/case folding and configurable normalization;
pin the intended algorithm because changing it may require a rebuild.

`normalized_update_values(Model, name=value)` prepares both source and derived
values for an ORM bulk UPDATE; direct SQL bypasses normal synchronization. It
rejects SQL expressions and explicit writes of derived values.

`rebuild_normalized_columns(Model, db_sess=session, batch_size=500)` includes
soft-deleted rows, pages by primary key and flushes but does not commit or close
the session. Use a dedicated maintenance session and coordinate existing writers.
Adding a declaration does not create a database column or backfill old rows.
`TruncateString` truncates stored values, so derived fields must use the same
stored-value contract. Avoid callable/server INSERT defaults that cannot be
normalized before insertion. See the function docstrings for supported sources,
length handling and migration examples.

## Authentication and authorization

`create_access_token(user)` creates a signed JWT containing a versioned identity:
the user ID and an HMAC stamp tied to its stored password hash. It does not put the
password hash itself in the token. Password change changes the stamp; strict
validation rejects a missing/soft-deleted user.

Two contracts are intentional:

| Operation | Database lookup | Guarantee |
| --- | --- | --- |
| `get_user_id_by_jwt_identity(identity)` | None | Extracts an ID from the expected identity format; it does not verify the JWT signature itself |
| `get_userId()` / `get_userId_required()` | None | Uses the request's JWT-derived ID; no current-user/revocation check |
| `get_user_by_jwt_identity(session, identity)` / `User.current` | Current user | Confirms the stored stamp and current user |
| `protected_route()` | No additional current-user lookup | Requires a correctly signed, unexpired JWT |
| `protected_route(check_user=True)` | Current user | Also requires strict current-user validation |
| `protected_route(perms=...)` | Current user/permissions | Requires strict user and the specified permissions |

Strict validation reads stored credential columns separately from cached ORM
attributes, without flushing or overwriting pending edits. Ordinary reads obey
the supplied Session's transaction isolation: an established REPEATABLE READ
snapshot remains a snapshot. For a locking current read use
`get_user_by_jwt_identity(..., for_update=True)` or
`User.get_current(for_update=True)`. This also refreshes the ORM row as described
under row locking; finish pending edits deliberately before that refresh.
`protected_route(check_user=True)` does not silently change transaction isolation
or acquire a user row lock. Returned ORM attributes retain normal Session cache
semantics unless a refresh was explicitly requested.

Only feed already verified claims to the pure identity helper. A fast route can
continue accepting a previously issued token until expiry after password change
or deletion. Important writes and sensitive reads should use strict checks.
Automatic renewal always rechecks current authorization: an old token must not be
extended indefinitely through a fast route. Existing long access-token lifetimes
are configurable; they are not silently shortened by this update.

Renewal reads the stored authorization fields as scalar values without autoflush
or replacing a cached ORM object. On MySQL it uses a current locking read, so a
previous repeatable-read snapshot cannot hide a committed password change. The
user row stays locked until the request transaction ends. Renewal uses the same
connection and never commits or rolls back the view's transaction. Keep request
transactions short and finish writes explicitly before returning a response.

Soft deletion followed by restoration with the same password can make an old,
unexpired token valid again. The library does not add a separate authVersion or
independent logout-all-sessions feature. Choose another session/revocation design
if those guarantees are required.

```python
from flask import Blueprint

bp = Blueprint("items", __name__)


@bp.post("/api/items")
@protected_route(perms=Operations.edit_items)
def edit_items():
    user = User.current
    # Validate DTO and apply project-specific access checks.
```

`perms` requires every operation; `perms_any` requires at least one. These checks do
not replace access checks for a particular event, tenant or record. JWTs are
cookie-based; retain CSRF protection and send the expected CSRF header for unsafe
browser requests. Production cookies require HTTPS and appropriate SameSite and
domain settings.

### Roles and permission checks

```python
user.has_any_role((Roles.admin, Roles.organizer))
user.has_permissions((Operations.view_items, Operations.edit_items))
user.has_any_permissions((Operations.view_items, Operations.edit_items))

# Compose with other writes in one transaction:
changed = user.set_roles(actor, (Roles.user, Roles.organizer), db_sess=db_sess, commit=False)
db_sess.commit()
```

`has_permissions` requires every requested operation; an empty iterable succeeds.
`has_any_permissions` requires at least one and returns False for an empty iterable.
The inherited checker reads the available operation set once per call. An overridden
`check_permission` remains authoritative, including through `protected_route`.
There is no persistent permission cache to invalidate.

`set_roles` accepts positive integer IDs and ignores duplicates. It audits only
memberships added/removed and returns whether the set changed. New memberships
must reference active roles. Existing singular add/remove methods use the same
transaction protocol. No-op calls do not commit unrelated work.

UserBase role writes lock the user row and read current memberships on databases
with row locks, including when the Session had an older MySQL snapshot. They may
flush the shared Session, even with `commit=False` or on a no-op. Locks last until
the transaction ends, including after a no-op; finish it explicitly before external calls. Low-level
`UserRole` or raw SQL writers must follow the same parent-lock protocol for
concurrent updates. SQLite does not prove those row-lock guarantees.
Rollback-safe relationship bookkeeping can invoke ORM flush/update callbacks
without a scalar `UPDATE User`; hooks should check actual attribute history.

MySQL can still select a deadlock victim, including for different users when
membership range/gap locks overlap. The helper does not retry or roll back a
caller-owned transaction. The outer owner must roll back and, where appropriate,
retry the entire command from a fresh Session; retrying only the last helper can
lose earlier work. Keep external effects outside any retried database command.

## HTTP policies and logging

`RequestPolicy` applies before reading the body:

```python
from flask import Blueprint

from bafser import RequestPolicy, request_policy

bp = Blueprint("public", __name__)


@bp.post("/api/public/orders")
@request_policy(RequestPolicy(
    max_content_length=64 * 1024,
    log_body=False,
    log_query=False,
    authenticate=False,
))
def create_order():
    payload = OrderInput.get_from_req()
    # Guest authorization and project logic go here.
```

`authenticate=True` enables optional user JWT lookup, log identity and cookie
renewal; it does not require login. `protected_route` requires login.
`authenticate=False` is for intentionally public/guest operations. It does not
authenticate a bank callback or buyer. The application implements that protocol.
Do not combine it with a route that requires user JWT authentication.
The standard current-user resolver also ignores the user cookie and any cached
user on this route, including locking lookups. An omitted audit actor is
therefore the system; an explicit actor remains explicit. A custom
`override_get_current_user` owns its authorization protocol and must respect the
chosen boundary when it delegates or supplies its own user.

Set the application's default through `AppConfig(REQUEST_POLICY=...)`. A route
policy specializes it before any parser reads the body, allowing a small JSON
limit for purchases and a larger one for administrative uploads. `None` fields in
a route policy inherit the application policy, so a logging-only override cannot
silently remove the body limit. Route `sensitive_fields` extend the application's
set. At application level, unspecified `authenticate` becomes `True`,
`max_log_length` becomes `2048`, body/query logging selects the dev/production
default, and an unspecified body limit keeps Flask's configured limit. Incoming
request limits still apply in dev.

For JSON with unknown length and a WSGI-terminated input stream, the helper reads
at most the limit plus one byte before parsing. Oversize input is rejected with
413 rather than accepting a valid truncated prefix; repeated parse attempts in
that request remain rejected. After the size check, JSON is limited to 256 nested
objects and arrays, counting the root container as level one. Greater depth
returns 400 Bad Request before JSON decoding or view execution. Non-JSON streams
keep the framework's bounded stream behavior; their parser and the edge server
also enforce the upload policy.
An early hook may inspect stream metadata without reading the body: the helper
rebuilds an already cached stream with the effective route limit. Hooks that
consume or parse the body must run after the request policy has been applied;
no later limit can undo earlier body consumption.

| Field | Purpose |
| --- | --- |
| `max_content_length` | Maximum accepted body bytes, or the application's configured limit |
| `log_body` | Enable/disable body logging; `None` inherits, then selects the mode default |
| `log_query` | Enable/disable query logging; `None` inherits, then selects the mode default |
| `body_fields` | Exact key allowlist for a root JSON object; other root shapes are omitted |
| `sensitive_fields` | Additional sensitive names to mask in production; extends the base policy |
| `max_log_length` | Bound production HTTP data and reduced diagnostic output; `None` inherits |
| `authenticate` | Whether optional request JWT processing is enabled; `None` inherits |

Production HTTP data logging defaults to metadata. Explicitly permitted bodies/queries use the same
redaction policy across request, response and error logs, including normalized
camelCase/snake_case names. Development diagnostics retain complete available
values and are not a safe production log. Streaming responses are not consumed
just to log them. SQL parameters are hidden by the default production engine setting.
An explicit `log_body=False` or `log_query=False` disables that diagnostic in dev
as well; `None` and `True` retain complete available dev data.
With `body_fields` set, production omits a root array or scalar entirely. Nested
values of an allowed field remain available subject to sensitive-name masking
and size limits. Overlong keys are omitted without recording their prefixes.
Allowlist matching is exact, including case and Unicode spelling; list aliases
explicitly when needed. Sensitive-name masking still normalizes camelCase and
snake_case variants independently of the allowlist.
Server logs keep ordinary messages, full tracebacks and exception chains by
default, including in production. `AppConfig(LOG_ERROR_DETAILS=False)` selects
reduced production diagnostics: owned formatters omit arbitrary message text and
exception values, retaining bounded exception locations/types. `DEV_MODE=True`
always keeps full details. The default is also full details before an application
has been configured; background jobs needing reduced output must load their
application configuration and use its app context.

`LOG_ERROR_DETAILS` does not enable body/query logging or change client error
responses. Full messages and exceptions are not scanned for secrets; values
explicitly interpolated by application code remain visible. Full messages and
tracebacks are not limited by `RequestPolicy.max_log_length`. An explicitly set
positive `create_log_handler(max_msg_len=...)` still limits the message text in
production, with the traceback kept separately. Dev keeps complete messages.
Failures of log formatting/writing also follow the detail switch, without dumping
the original record or turning logging failures into HTTP failures. In reduced mode,
if application code intentionally emits a
constant safe message or data already processed by `bafser.logger.format_log_data`,
it marks that record with `extra={"bafser_safe_message": True}`. This is a trust
boundary, not a secret scanner: never mark interpolated credentials or raw provider
payloads safe. `format_log_data` returns `None` when body logging is disabled.
Explicit production query logging retains names with every value masked; dev
logging retains the actual available path/query.
In production, formatter `outer_args` may add custom fields but cannot replace
the HTTP metadata fields (`json`, `url`, `uid` and the other built-in fields).

Shared files require `MULTIPROCESS_LOGGING=True`. Rotation limits stored archives;
the reader understands supported current and legacy archive names. Application
code can use existing named logger helpers; global logging configuration is an
explicit application concern. Dashboard work is bounded rather than scanning an
ever-growing log history on every request.

`AppConfig(CONFIGURE_ROOT_LOGGING=False)` leaves general error logging to the host
while configuring the library's named loggers. The lower-level
`bafser.logger.setLogging(configure_root=False)` provides the same logger choice.
Existing non-bafser handlers are not
removed; their privacy policy remains the embedding application's responsibility.
Dashboard bounds are ordinary application config values set through
`AppConfig.add`: `DASHBOARD_WINDOW_HOURS=24`, `DASHBOARD_MAX_BYTES=2097152`,
`DASHBOARD_MAX_LINES=20000` and `DASHBOARD_MAX_FILES=6` by default. These independent
bounds limit the selected time window, read volume and retained samples.

The dashboard shows request/error counts, p50/p95 latency, traffic/error trends,
endpoint statistics and recent 4xx/5xx requests with request IDs. Period, endpoint
and status filters apply to every panel. Durations measure the server work up to
the logging hook, not client download/streaming time. Legacy rows without a status
remain explicitly unknown rather than counted as successful requests.

`DASHBOARD_CACHE_SECONDS=3` keeps one bounded snapshot per app/process to reduce
repeated file reads; zero disables the cache. `DASHBOARD_RECENT_LIMIT=50` bounds the
recent failure list. Manual refresh can request a new snapshot. The page displays
the requested/observed range, snapshot age and read limits; a bounded tail is not
a complete historical monitoring database. Incomplete trailing records are omitted
and reported separately, so a partially written row cannot become a legacy sample.
No background collector or external
CDN is needed. The app still owns the dashboard route and its permission check;
the statistics page does not display raw request bodies, IPs or exception traces.

## Database migrations

Use Alembic for an evolving production schema:

```sh
bafser alembic init
bafser alembic revision initial
bafser alembic upgrade
```

Revision generation compares the development database with model metadata.
Review every generated migration. `upgrade` targets development by default;
`bafser alembic upgrade --prod` selects production configuration. `--setup` also
performs the configured upgrade before database initialization/permission sync.

Compatible migrations may be applied while the old version is serving requests.
For an incompatible migration, stop old writers and complete active operations
before changing the schema. The library does not orchestrate deployment, backup
or traffic draining. A code rollback does not roll back schema changes or restore
financial transactions.

## Deployment and security

Keep simple development straightforward, but make production choices explicit:

1. **Startup.** Set `AUTO_SETUP=False` for runtime. Execute `python main.py --setup`
   once against the intended database/storage, then start WSGI and workers. Keep
   setup serialized and check the selected schema before serving traffic.
2. **Persistent files.** Use the same absolute storage paths for setup, web and
   background jobs. Existing JWT/API keys must survive code releases. Normal
   runtime reads required nonempty keys; bootstrap creates them safely. Do not
   silently recover from a wrong path by issuing a new key.
   Creating a new key requires hard links on the storage filesystem; reading an
   existing key does not. An unsupported filesystem fails without replacing a key.
3. **Processes and resources.** Use a production WSGI server and enable safe
   multi-process logs when sharing files. Size pools/timeouts per process and
   account limits. Verify the actual host's reload mechanism; replacing a WSGI
   file alone is not a universal promise about all imported Python modules.
4. **Requests.** Configure early body limits, bounded lists/strings and strict DTOs.
   Enforce guest and entity-specific permissions in the application. Bank secrets,
   buyer tokens and personal data do not belong in URL queries or public catalogs.
5. **Authentication.** Use strict user checks for important endpoints. Preserve
   cookie CSRF, HTTPS and appropriate cookie flags. Understand the delayed-revocation
   contract of fast routes and configure access lifetime/refresh threshold together.
6. **Proxy, hosts and CORS.** Trust only known proxy hops; an arbitrary forwarded IP
   header is not a security identity. Configure allowed hosts/origins in the app or
   trusted frontend proxy. Credentialed CORS needs explicit trusted origins.
7. **Logs.** Use production logging policy, retention and restricted file access.
   Full dev logs may contain submitted credentials and other raw values; use that
   mode deliberately for debugging. File/body logs do not replace durable audit
   records required by the application.
8. **Updates and recovery.** Back up the database and persistent resources together
   according to a tested recovery procedure. Run a real safe API/database smoke
   check after activation, not only a check of a source path or release string.

No Redis, queue framework or payment provider is required by bafser. If an
application uses a queue, external provider or mail service, it owns their
timeouts, idempotency, retry/reconciliation and durable operation state. Do not
hold database locks while waiting for those services.

## Testing and release checks

Ruff policy lives in `pyproject.toml`: 150-character lines, correctness checks and
explicit narrow exceptions. In VS Code, `ruff.configurationPreference="filesystemFirst"`
keeps user-level ignores from overriding that project policy.

The repository's fast suite is:

```sh
python -m unittest discover -s test -v
python -m ruff check src test
pyright --project test/typing
```

The optional real-database tests require an isolated disposable MySQL database
selected by `BAFSER_TEST_MYSQL_URL`. `python -m test.run_mysql_ci` requires that
setting, runs the real-lock suite and fails on skips. Never point this suite at an
application database.

CI runs Python 3.10/3.14 on PRs and develop, the full supported matrix on release
tags, a required MySQL job and installed wheel/sdist smoke checks. Artifact checks
run away from the checkout and verify templates, typing metadata and no writes
from a plain import or CLI help. Publishing is limited to release tags after all
required jobs succeed. CI definitions do not claim a particular local run passed.
