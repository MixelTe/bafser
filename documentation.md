# Bafser Framework Documentation

## 1. Core Concepts & Philosophy

Bafser (Base for Flask Server) is a lightweight, opinionated framework built on top of Flask and SQLAlchemy, designed to accelerate development of secure, scalable web applications with built‑in authentication, authorization, logging, and database management.

### What Problem Does Bafser Solve?

Building a production‑ready Flask application requires integrating many separate components: JWT authentication, role‑based access control, database session management, Alembic migrations, structured logging, API documentation generation, and a consistent project layout. Bafser provides a cohesive, batteries‑included foundation that handles these concerns out of the box, allowing developers to focus on business logic rather than boilerplate.

### Architectural Principles

1. **Convention over Configuration**
   Bafser expects a specific project structure (e.g., `blueprints/`, `data/`) and provides base classes (`TablesBase`, `RolesBase`, `OperationsBase`) that automatically discover and validate your custom definitions. This reduces decision fatigue and ensures consistency across projects.

2. **Security by Default**
   - JWT tokens stored in HTTP‑only cookies (CSRF‑protected).
   - Automatic password hashing (bcrypt) for user accounts.
   - Built‑in permission system that ties operations to roles and users.
   - Soft‑delete (`ObjMixin`) with audit logging for all data changes.

3. **Database‑Agnostic Core**
   Supports SQLite (for development) and MySQL (for production) via a unified SQLAlchemy layer. Alembic migrations are integrated and can be toggled with a single config flag.

4. **Observability Built‑In**
   Comprehensive logging across four distinct channels:
   - **Request/Response logs** (CSV) for API auditing.
   - **Error logs** (plain text) for debugging.
   - **Front‑end client logs** for capturing browser‑side issues.
   - **Dashboard metrics** (CSV) for performance monitoring.
   Logs include user ID, IP address (with emoji representation), request duration, and JSON payloads (with sensitive fields masked).

5. **Developer Experience**
   - CLI tool (`bafser`) for common tasks (create project, add users, manage roles, run migrations).
   - Automatic API documentation generation via the `@doc_api` decorator.
   - Hot‑reload in development mode, delayed‑request simulation for testing UI loaders.
   - Type hints throughout, enabling full IDE support and static analysis.

### How It Differs from Plain Flask

| Aspect | Plain Flask | Bafser |
|--------|-------------|--------|
| **Authentication** | Manual setup of Flask‑JWT‑Extended | Pre‑configured JWT with cookie storage, refresh tokens, and identity helpers |
| **Authorization** | Custom decorators or extensions | Declarative operations & roles, built‑in permission system |
| **Database** | SQLAlchemy setup per project | Unified session management, mixins for CRUD, automatic table discovery |
| **Logging** | Requires separate handlers | Four‑channel logging with structured CSV/JSON output |
| **Project Layout** | Up to the developer | Enforced blueprint/data/script structure |
| **API Docs** | Manual or third‑party (Swagger) | Automatic from type hints via `@doc_api` |
| **CLI** | Flask‑CLI or custom scripts | Integrated `bafser` with user/role management and migration commands |

### Key Design Patterns

- **Mixins over Inheritance** – Table models compose `IdMixin`, `ObjMixin`, `SingletonMixin`, or `BigIdMixin` to add common functionality without deep inheritance trees.
- **Dependency Injection via Flask’s `g`** – Database sessions and current user are automatically attached to the request context (`g.db_session`, `g.userId`).
- **Decorator‑Based Security** – Use `@protected_route` to guard endpoints; permissions are checked via the built‑in permission system.
- **Configuration as Code** – `AppConfig` class allows fluent addition of secret keys, data folders, and environment‑specific settings.
- **Soft‑Delete with Audit Trail** – Deleting a record sets a `deleted` flag and logs the action with actor and timestamp; restoration is equally tracked.

### Philosophy

Bafser believes that a framework should **guide, not restrict**. It provides strong defaults and conventions but remains extensible—every base class can be subclassed and overridden, every config value can be changed, and the underlying Flask app is fully accessible. The goal is to eliminate the repetitive, error‑prone parts of backend development while keeping the power of Flask and SQLAlchemy within reach.

## 2. Getting Started

This guide walks you through setting up a new Bafser project, from installation to running your first API endpoint.

### Prerequisites

- Python 3.12 or later
- pip (Python package manager)
- (Optional) MySQL if you plan to use a production database

### Installation

Bafser is distributed as a Python package. Install it directly from your project’s directory:

```bash
pip install bafser
```

Alternatively, if you are developing within a clone of the Bafser repository, you can install in editable mode:

```bash
pip install -e /path/to/bafser
```

### Creating a New Project

Bafser provides a CLI command to scaffold a project with the recommended structure:

```bash
bafser init_project
```

This will create the following files and directories:

```
.
├── bafser_config.py           # Configuration file (copied from example)
├── main.py                    # Entry point of your application
├── requirements.txt           # Python dependencies
├── blueprints/                # Flask blueprints (API endpoints)
│   └── api.py                 # Example blueprint
├── data/                      # SQLAlchemy models and domain definitions
│   ├── _tables.py            # Table name constants
│   ├── _roles.py             # Role definitions
│   ├── _operations.py        # Operation definitions
│   └── user.py               # Custom User model
└── storage/                   # Auto‑created for logs, images, secrets
```

### Configuration

Edit `bafser_config.py` to match your environment:

```python
db_dev_path = "storage/dev.db"      # SQLite database for development
db_path = "ENV:DBPATH"              # Production database (set via environment variable)
db_mysql = True                     # Use MySQL in production, SQLite in development
sql_echo = False                    # Print SQL queries to console

use_alembic = True                  # Enable Alembic migrations
migrations_folder = "alembic"       # Where migration scripts are stored

# Logging paths
log_info_path = "storage/logs/log_info.csv"
log_requests_path = "storage/logs/log_requests.csv"
log_errors_path = "storage/logs/log_errors.log"
log_frontend_path = "storage/logs/log_frontend.log"
log_dashboard_path = "storage/logs/log_dashboard.csv"

# Security & storage
jwt_key_file_path = "storage/secret_key_jwt.txt"
images_folder = "storage/images"

# URLs
login_page_url = "/login"
api_url = "/api/"

# Project structure
blueprints_folder = "blueprints"
data_tables_folder = "data"
```

### The Application Entry Point

`main.py` is where your app is created and configured. A typical minimal version looks like this:

```python
import sys
from datetime import timedelta

from bafser import AppConfig, create_app
from dotenv import load_dotenv

from scripts.init_db import init_db
from scripts.init_dev_values import init_dev_values

load_dotenv()

app, run = create_app(__name__, AppConfig(
    DEV_MODE="dev" in sys.argv,
    DELAY_MODE="delay" in sys.argv,
))

run(__name__ == "__main__", init_db, init_dev_values)
```

### Running the Server

#### Development Mode

Start the server with hot‑reload and SQLite:

```bash
python main.py dev
```

The server will be available at `http://127.0.0.1:5000`.

#### Production Mode

For production, use a WSGI server like Gunicorn (recommended) with `THREADED=True` in `AppConfig`:

```bash
gunicorn -w 4 --threads 2 --worker-class gthread -b 0.0.0.0:80 main:app
```

You can also run without the `dev` argument:

```bash
python main.py
```

This will use the production database (MySQL if configured) and disable debug features.

### Your First API Endpoint

1. Open `blueprints/api.py` (or create a new blueprint).
2. Define a route using the `@doc_api` decorator to auto‑generate documentation:

```python
from bafser import doc_api, protected_route
from flask import Blueprint, jsonify

bp = Blueprint("example", __name__)

@bp.get("/api/hello")
@doc_api(res=str, desc="A friendly greeting")
def hello():
    return jsonify("Hello, Bafser!")
```

3. The endpoint will be automatically registered. Start the server and visit `http://127.0.0.1:5000/api/hello` to see the response.

### Next Steps

- Define your data models in `data/` using the provided mixins (`IdMixin`, `ObjMixin`, etc.).
- Create roles and operations in `data/_roles.py` and `data/_operations.py`.
- Use `@protected_route` to secure endpoints.
- Explore the built‑in logging and dashboard features.

## 3. API Reference

This section documents all public modules, classes, functions, and methods provided by Bafser. The framework is organized into several logical groups:

- **Application Factory** (`create_app`, `AppConfig`)
- **Database & Models** (`SqlAlchemyBase`, mixins, `TablesBase`, `RolesBase`, `OperationsBase`)
- **Authentication & Authorization** (`create_access_token`, `protected_route`)
- **Utilities** (`get_json_values`, `response_msg`, `randstr`, etc.)
- **Logging** (`get_logger_frontend`, `log_frontend_error`, `ParametrizedLogger`)
- **API Documentation** (`doc_api`, `get_api_docs`, `render_docs_page`)
- **CLI** (`bafser` command)

Each entry includes its signature, parameters, return type, and a brief description.

---

### 3.1 Application Factory

#### `AppConfig`

*Class* `bafser.AppConfig`

Configuration container for the Bafser application. Used to set up frontend paths, JWT settings, static folders, and more.

**Constructor**
`AppConfig(*, FRONTEND_FOLDER: str = "build", JWT_ACCESS_TOKEN_EXPIRES: Literal[False] | timedelta = timedelta(hours=24), JWT_ACCESS_TOKEN_REFRESH: Literal[False] | timedelta = timedelta(minutes=30), CACHE_MAX_AGE: int = 31536000, MESSAGE_TO_FRONTEND: str = "", STATIC_FOLDERS: list[str] = ["/static/", "/fonts/", "/_next/"], DEV_MODE: bool = False, DELAY_MODE: bool = False, PAGE404: str = "index.html", HEALTH_ROUTE: bool | str = False, THREADED: bool = False)`

**Methods**
- `add(key: str, value: Any) -> AppConfig` – Adds a key‑value pair to Flask’s `app.config`.
- `add_data_folder(key: str, path: str) -> AppConfig` – Ensures the folder exists at startup and adds it to config.
- `add_secret_key(key: str, path: str) -> AppConfig` – Loads a secret from a file and adds it to config.
- `add_secret_key_env(key: str, envname: str | None = None, default: str | None = None) -> AppConfig` – Reads a secret from an environment variable.
- `add_secret_key_rnd(key: str, path: str) -> AppConfig` – Generates a random secret, stores it in a file, and adds it to config.

#### `create_app`

*Function* `bafser.create_app(import_name: str, config: AppConfig) -> tuple[Flask, Callable]`

Creates and configures a Flask application with all Bafser features enabled.

**Parameters**
- `import_name` – The Flask application import name (usually `__name__`).
- `config` – An instance of `AppConfig`.

**Returns**
A tuple `(app, run)` where:
- `app` is the Flask application instance.
- `run` is a function that starts the server (or performs setup) when called.

**The `run` function**
`run(run_server: bool, init_db: Callable[[Session, AppConfig], None] | None = None, init_dev_values: Callable[[Session, AppConfig], None] | None = None, port: int = 5000, host: str = "127.0.0.1")`

If `run_server=True`, the server starts. If `THREADED=True` and `--setup` is in `sys.argv`, only database initialization is performed.

#### `update_message_to_frontend`

*Function* `bafser.update_message_to_frontend(msg: str) -> None`

Updates the global message that will be sent to the front‑end via a cookie. Useful for broadcasting maintenance notices or announcements.

#### `get_app_config`

*Function* `bafser.get_app_config() -> AppConfig`

Returns the currently active `AppConfig` instance. Must be called after `create_app`.

---

### 3.2 Database & Models

#### `SqlAlchemyBase`

*Class* `bafser.SqlAlchemyBase`

Base class for all SQLAlchemy models. Inherits from `DeclarativeBase`, `SerializerMixin`, and `MappedAsDataclass`. Provides:

- `get_dict() -> object` – Returns a serialized dictionary of the object.
- `get_session() -> Session | None` – Returns the SQLAlchemy session the object is bound to.
- `db_sess` property – Returns the session (raises `AssertionError` if not bound).

#### Mixins

**`IdMixin`**
Adds an integer primary key `id` and provides class methods for querying:
`query(db_sess, for_update=False)`, `get(db_sess, id, for_update=False)`, `all(db_sess, for_update=False)`.
Also includes `query2`, `get2`, `all2` variants that automatically retrieve the session from the global context.

**`ObjMixin`**
Extends `IdMixin` with a `deleted` flag for soft‑delete. Overrides query methods to exclude deleted rows by default (`includeDeleted` parameter).
Provides `delete(actor, commit=True, now=None, db_sess=None)` and `restore(actor, ...)` with audit logging via `Log`.
Customizable via `_on_delete` and `_on_restore` hooks.

**`SingletonMixin`**
Ensures a table contains exactly one row. Provides `get(db_sess, commit=True)` that returns the singleton instance, creating and initializing it if missing. Override `init()` for custom initialization.

**`BigIdMixin`**
Adds a unique short string identifier `id_big` (8 characters). Provides `get_by_big_id(id_big, includeDeleted=False, db_sess=None)` and `set_unique_big_id(db_sess=None)` to generate a collision‑free ID.

#### `TablesBase`

*Class* `bafser.TablesBase`

Base class for table‑name constants. Defines default tables: `User`, `Role`, `UserRole`, `Image`.
Subclass and add your own table names as class attributes (e.g., `MyTable = "my_table"`).
`get_all()` returns a list of `(attribute_name, table_name)` pairs.

#### `RolesBase`

*Class* `bafser.RolesBase`

Base class for role definitions. The built‑in `admin` role has ID `1`.
Subclass and add integer constants for each role (e.g., `editor = 2`).
Set `ROLES` dictionary mapping role IDs to `{"name": "...", "operations": [...]}`.
`get_all()` returns `[(id, name), ...]` for all defined roles.

#### `OperationsBase`

*Class* `bafser.OperationsBase`

Base class for operation definitions. Each operation is a tuple `(id, description)`.
Subclass and add class attributes like `view_items = ("view_items", "Can view items")`.
`get_all()` returns a list of `(id, description)` tuples.

#### `UserBase`

*Class* `bafser.UserBase`

Abstract user model. Provides login, password hashing, role management, and permission checking.
**Important methods:**
- `new(creator, login, password, name, roles, **kwargs)` – Creates a new user.
- `get_by_login(db_sess, login, includeDeleted=False)` – Retrieves a user by login.
- `check_password(password)` – Verifies a plain‑text password.
- `set_password(password)` – Updates the password hash.
- `get_roles()` – Returns `[(role_id, role_name)]` for the user.
- `has_operation(operation_id)` – Checks if the user has a specific operation.
- `current` property – Returns the currently authenticated user (from request context).

Subclass `UserBase` to add custom columns; override `_new` and `new` to pass extra arguments.

#### `UserRole`, `Role`, `Image`, `Log`

Predefined models for linking users to roles, role definitions, image storage, and audit logging.
See the source for detailed fields and methods.

---

### 3.3 Authentication & Authorization

#### `create_access_token`

*Function* `bafser.create_access_token(user: UserBase) -> str`

Creates a JWT access token for the given user. The token is stored in an HTTP‑only cookie automatically.

#### `get_user_by_jwt_identity`

*Function* `bafser.get_user_by_jwt_identity(db_sess: Session, jwt_identity: Any, *, lazyload: bool = False, for_update: bool = False) -> UserBase | None`

Retrieves a user from a JWT identity (parsed from the token). Returns `None` if the token is invalid or the user does not exist.

#### `get_user_id_by_jwt_identity`

*Function* `bafser.get_user_id_by_jwt_identity(jwt_identity: Any) -> int | None`

Extracts the user ID from a JWT identity without hitting the database.

#### `protected_route`

*Decorator* `bafser.protected_route()`

Flask route decorator that ensures the request contains a valid JWT. If not, returns a 401 Unauthorized response (or redirects to the login page for non‑API routes).


---

### 3.4 Utilities

#### JSON Handling

- `get_json(request) -> tuple[dict | list, bool]` – Parses JSON from the request body; returns `(data, success)`.
- `get_json_values(json: dict, *specs: tuple[str, type]) -> tuple[list, str | None]` – Extracts values from a dictionary according to a specification. Returns `(values, error_message)`.
- `get_json_list(json: dict, *specs: tuple[str, type]) -> tuple[list[list], str | None]` – Extracts a list of lists.
- `get_json_values_from_req(request, *specs)` / `get_json_list_from_req` – Convenience wrappers that combine `get_json` and `get_json_values`.

#### Response Helpers

- `response_msg(message: str, status: int = 200) -> Response` – Returns a JSON response `{"message": message}` with the given HTTP status.
- `response_not_found() -> Response` – Returns a 404 JSON response.
- `abort_if_none(value: T | None | type["Undefined"], name: str) -> T` – Aborts request with 400 code if value is None or Undefined
- `create_file_response(path: str, mimetype: str | None = None) -> Response` – Serves a file with appropriate headers.
- `jsonify_list(items: list) -> Response` – JSON‑ifies a list of SQLAlchemy models (calls `get_dict` on each).

#### Database & Session

- `get_db_session() -> Session` – Returns the current request’s database session (creates one if missing).
- `override_get_db_session(func: Callable) -> None` – Overrides the default session factory (advanced).
- `use_db_session(func)` / `use_db_sess(func)` – Decorators that inject a database session as the first argument to the function.

#### Security & Randomness

- `get_secret_key(path: str) -> str` – Reads a secret key from a file.
- `get_secret_key_rnd(path: str) -> str` – Generates a random secret key and stores it in the file (if not exists).
- `randstr(length: int = 8) -> str` – Generates a random alphanumeric string.

#### Date & Parsing

- `get_datetime_now() -> datetime` – Returns a timezone‑aware UTC datetime.
- `parse_date(s: str) -> datetime | None` – Attempts to parse a date string in multiple formats.

#### Miscellaneous

- `create_folder_for_file(filepath: str) -> None` – Ensures the parent directory of a file exists.
- `ip_to_emoji(ip: str) -> str` / `emoji_to_ip(emoji: str) -> str` – Converts an IP address to a unique emoji sequence and back (for log readability).
- `listfind(lst: list, predicate: Callable) -> Any | None` – Returns the first element in a list that satisfies the predicate.
- `get_all_values(obj) -> list` / `get_all_fields(obj) -> list[tuple[str, Any]]` – Introspect an object’s class attributes.

---

### 3.5 Logging

#### `get_logger_frontend`, `get_logger_requests`, `get_logger_dashboard`

*Functions* returning configured `logging.Logger` instances for each log channel.

#### `log_frontend_error`

*Function* `bafser.log_frontend_error(msg: str | None = None)`

Logs a front‑end error with the current request context.

#### `ParametrizedLogger`

*Class* `bafser.ParametrizedLogger`

Base class for creating loggers that automatically attach extra arguments. Override `_get_args()` to return a dictionary of context.

#### `add_logger`

*Function* `bafser.add_logger(name: str, handler: logging.Handler) -> logging.Logger`

Registers a custom logger with a dedicated handler.

#### `create_log_handler`

*Function* `bafser.create_log_handler(fpath: str, format: str = ..., level: int = ..., **kwargs) -> logging.Handler`

Creates a rotating file handler (or watched file handler in threaded mode) with a `RequestFormatter`.

---

### 3.6 API Documentation

#### `doc_api`

*Decorator* `bafser.doc_api(*, req: Any = None, res: Any = None, desc: str | None = None, jwt: bool | None = None)`

Attaches type information to a Flask route for automatic documentation generation.
`req` and `res` are Python types (e.g., `UserDict`, `list[str]`).
If `jwt=False`, the endpoint is marked as not requiring authentication.

#### `get_api_docs`

*Function* `bafser.get_api_docs() -> dict[str, Any]`

Returns a JSON‑serializable dictionary of all documented endpoints and their type definitions.

#### `render_docs_page`

*Function* `bafser.render_docs_page() -> str`

Renders an HTML page that interactively displays the API documentation. Mount this route to `/docs` or similar.

#### `JsonObj`, `JsonOpt`, `Undefined`, `JsonParseError`

Utilities for defining JSON‑serializable objects with optional fields and validation.

---

### 3.7 CLI

The `bafser` command provides the following subcommands:

- `init_project` – Scaffolds a new Bafser project.
- `add_user_role <userId> <roleId> [dev]` – Assigns a role to a user.
- `add_user <login> <password> <name> <roleId> [dev]` – Creates a new user.
- `change_user_password <login> <new_password> [dev]` – Updates a user’s password.
- `remove_user_role <userId> <roleId> [dev]` – Removes a role from a user.
- `alembic <init | revision | upgrade>` – Manages database migrations.
- `configure_webhook <set | delete> [dev]` – (If `bafser_tgapi` is installed) Configures Telegram webhooks.
- `stickers` – (If `bafser_tgapi` is installed) Manages sticker packs.

Run `bafser` without arguments to see the full list.

## 4. Guides & Tutorials

This section provides practical, step‑by‑step examples of common tasks you’ll encounter when building a Bafser application. The examples are based on real‑world patterns extracted from the included example project.

### 4.1 Building a Basic CRUD Application

Let’s create a simple “Task” model with endpoints to create, read, update, and delete tasks.

#### Step 1: Define the Table

Create `data/task.py`:

```python
from bafser import SqlAlchemyBase, ObjMixin
from data._tables import Tables
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

class Task(SqlAlchemyBase, ObjMixin):
    __tablename__ = Tables.Task   # we’ll define Tables.Task later

    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    completed: Mapped[bool] = mapped_column(default=False)

    def get_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "completed": self.completed,
            "deleted": self.deleted,
        }
```

#### Step 2: Add Table Name Constant

Edit `data/_tables.py` (subclass `TablesBase` if you haven’t already):

```python
from bafser import TablesBase

class Tables(TablesBase):
    Task = "Task"
    # ... your other tables
```

#### Step 3: Create a Blueprint

Create `blueprints/task.py`:

```python
from bafser import abort_if_none, doc_api, protected_route, get_json_values_from_req, response_msg, jsonify_list, use_db_sess, Log
from flask import Blueprint, request
from data.task import Task

bp = Blueprint("task", __name__)

@bp.post("/api/task")
@doc_api(
    req={"title": str, "description": str},
    res=Task,
    desc="Create a new task"
)
@protected_route()
@use_db_sess
def create(db_sess: Session):
    values, error = get_json_values_from_req(request, ("title", str), ("description", str))
    if error:
        return response_msg(error, 400)
    title, description = values
    task = Task(title=title, description=description)
    db_sess.add(task)
    db_sess.commit()
    return task.get_dict()

```
**Alternative: Using `JsonObj` for structured request parsing**

Instead of manually extracting fields with `get_json_values_from_req`, you can define a `JsonObj` subclass that describes the expected request shape. This provides automatic validation, type conversion, and a clean object‑oriented interface.

First, define a request schema in your blueprint (or a separate module):

```python
from bafser import JsonObj, JsonOpt, Undefined

class CreateTaskRequest(JsonObj):
    title: str
    description: JsonOpt[str] = Undefined  # optional field
```

Then use it in the endpoint:

```python
@bp.post("/api/task")
@doc_api(
    req=CreateTaskRequest,
    res=Task,
    desc="Create a new task",
    jwt=True
)
@protected_route()
def create():
    req = CreateTaskRequest.get_from_req()
    # req is already validated; fields are accessible as attributes
    task = Task(title=req.title, description=Undefined.default(req.description, ""))
    Log.added(task)  # Log.added makes commit
    return task.get_dict()
```

`JsonObj.get_from_req()` automatically parses the JSON body, validates it against the schema, and returns a `JsonObj` instance. If validation fails, it aborts with a 400 error and a descriptive message. This approach is especially useful for complex nested structures, optional fields, and re‑usable request schemas across multiple endpoints.

```python
class TaskDict(TypedDict):
    id: int
    title: str
    description: str

@bp.get("/api/task")
@doc_api(res=list[TaskDict], desc="List all tasks")
@protected_route()
def list_tasks():
    return jsonify_list(Task.all2())

@bp.patch("/api/task/<int:task_id>")
@doc_api(req={"completed": bool}, res=TaskDict, desc="Update a task")
@protected_route()
def update(task_id):
    values, error = get_json_values_from_req(request, ("completed", bool))
    if error:
        return response_msg(error, 400)
    completed, = values
    task = Task.get2(task_id)
    if not task:
        return response_msg("Task not found", 404)
    task.completed = completed
    task.db_sess.commit()
    return task.get_dict()

@bp.delete("/api/task/<int:task_id>")
@doc_api(res=None, desc="Delete a task")
@protected_route()
def delete(task_id):
    task = abort_if_none(Task.get2(task_id), "task")
    task.delete2()  # soft‑delete with audit log
    return "", 204
```

#### Step 4: Register the Blueprint

Blueprints are automatically discovered if placed in the `blueprints/` folder (configurable via `blueprints_folder`). Ensure your blueprint is imported somewhere (or use `register_blueprints` manually). The default `register_blueprints` scans the folder, so just creating the file is enough.

#### Step 5: Test the API

Start the server with `python main.py dev` and use curl or a tool like Postman:

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"title":"Learn Bafser","description":"Read the docs"}' \
  http://localhost:5000/api/task
```

### 4.2 Configuration Management

Bafser’s `AppConfig` allows you to add custom configuration values that become available in `current_app.config`.

#### Adding a Custom Config Value

In `main.py`:

```python
app, run = create_app(__name__, AppConfig(...)
    .add("MAX_TASK_LIMIT", 100)
    .add_data_folder("UPLOAD_FOLDER", "storage/uploads")
    .add_secret_key_env("STRIPE_API_KEY")
)
```

Now you can access these values anywhere:

```python
from flask import current_app
limit = current_app.config["MAX_TASK_LIMIT"]
```

#### Environment‑Specific Configuration

Use the `DEV_MODE` flag to toggle settings:

```python
AppConfig(
    DEV_MODE="dev" in sys.argv,
    CACHE_MAX_AGE=604800 if not ("dev" in sys.argv) else 60,
)
```

### 4.3 Extending Core Functionality

#### Customizing the User Model

Suppose you need to add a `phone` field to the User model and enforce uniqueness.

Edit `data/user.py`:

```python
from typing import Any, override
from sqlalchemy import String
from sqlalchemy.orm import Mapped, Session, mapped_column
from bafser import UserBase, UserKwargs

class User(UserBase):
    phone: Mapped[str] = mapped_column(String(20), unique=True, default="")

    @classmethod
    @override
    def new(cls, creator: UserBase, login: str, password: str, name: str, roles: list[int], phone: str, *, db_sess: Session | None = None):
        return super().new(creator, login, password, name, roles, db_sess=db_sess, phone=phone)

    @classmethod
    @override
    def _new(cls, db_sess: Session, user_kwargs: UserKwargs, *, phone: str, **kwargs: Any):
        return User(**user_kwargs, phone=phone)

    @classmethod
    @override
    def create_admin(cls, db_sess: Session):
        fake_creator = User.get_fake_system()
        return User.new(fake_creator, "admin", "admin", "Admin", [Roles.admin], "", db_sess=db_sess)
```

#### Adding a Custom Logger

Create a logger that writes to a separate CSV file for business events:

```python
from bafser import add_logger, create_log_handler

handler = create_log_handler(
    "storage/logs/business_events.csv",
    "%(asctime)s;%(user_id)s;%(event)s;%(details)s",
    outer_args=["user_id", "event", "details"]
)
business_logger = add_logger("business", handler)

# Usage
business_logger.info("", extra={"user_id": 42, "event": "purchase", "details": "item_id=123"})
```

### 4.4 Debugging and Logging

#### Viewing Logs in Development

All logs are written to the `storage/logs/` directory. You can tail them in real‑time:

```bash
tail -f storage/logs/log_requests.csv
```

The CSV columns are: `reqid;ip;uid;asctime;method;url;message;code;json`.

#### Adding Custom Log Messages

Use the request‑aware loggers:

```python
from bafser import get_logger_requests

logger = get_logger_requests()
logger.info("Custom log message")
```

The message will appear in `log_requests.csv` with the current request’s ID, IP, user ID, etc.

#### Debugging Database Queries

Set `sql_echo = True` in `bafser_config.py` to see every SQL statement printed to the console.

### 4.5 Authentication Flows

#### Implementing a Login Endpoint

Bafser already provides JWT authentication via cookies, but you may want a custom login that returns additional user data.

Create `blueprints/auth.py`:

```python
from bafser import create_access_token, get_json_values_from_req, response_msg
from flask import Blueprint, jsonify
from data.user import User

bp = Blueprint("auth", __name__)

@bp.post("/api/login")
def login():
    values, error = get_json_values_from_req(request, ("login", str), ("password", str))
    if error:
        return response_msg(error, 400)
    login, password = values
    user = User.get_by_login2(login)
    if not user or not user.check_password(password):
        return response_msg("Invalid credentials", 401)
    token = create_access_token(user)
    response = jsonify(user.get_dict())
    response.set_cookie("access_token_cookie", token, httponly=True)
    return response
```

#### Protecting Routes with Permissions

Define an operation in `data/_operations.py`:

```python
from bafser import OperationsBase

class Operations(OperationsBase):
    task_create = ("task_create", "Can create tasks")
    task_delete = ("task_delete", "Can delete tasks")
```

Assign the operation to a role in `data/_roles.py`:

```python
from bafser import RolesBase
from data._operations import Operations

class Roles(RolesBase):
    manager = 2

Roles.ROLES = {
    Roles.manager: {
        "name": "Manager",
        "operations": [Operations.task_create, Operations.task_delete]
    }
}
```

Now protect the endpoint:

```python
from bafser import protected_route
from data.user import User

@bp.post("/api/task")
@protected_route(perms=Operations.task_create)
def create_task():
    user = User.current
    ...
```

### 4.6 Using the Dashboard

Bafser includes a built‑in dashboard that shows request metrics. Enable it by adding a route in your `main.py` (or a blueprint):

```python
from bafser import render_dashboard_page

@app.route("/dashboard")
def dashboard():
    return render_dashboard_page()
```

Visit `/dashboard` to see a table of recent requests with duration, status codes, and IP addresses.

### 4.7 Database Migrations with Alembic

If `use_alembic = True` in `bafser_config.py`, you can manage migrations via the CLI:

```bash
bafser alembic init          # creates the alembic folder (first time only)
bafser alembic revision      # generate a new migration script
bafser alembic upgrade       # apply all pending migrations
```

Migrations are automatically run when the server starts (unless `THREADED=True` and `--setup` is used).

## 5. Best Practices & Patterns

### 5.1 Project Structure

Keep your code organized according to Bafser’s conventions:

```
project/
├── blueprints/          # Flask blueprints, grouped by feature
│   ├── auth.py
│   ├── tasks.py
│   └── admin.py
├── data/                # SQLAlchemy models and domain definitions
│   ├── _tables.py      # table name constants
│   ├── _roles.py       # role definitions
│   ├── _operations.py  # operation definitions
│   ├── user.py         # extended User model
│   └── *.py            # other models
├── scripts/             # one‑off scripts and initialization
│   ├── init_db.py
│   └── init_dev_values.py
├── storage/             # generated files (logs, images, secrets)
│   ├── logs/
│   ├── images/
│   └── secret_*.txt
├── bafser_config.py     # configuration
├── main.py              # application entry point
└── requirements.txt     # dependencies
```

### 5.2 Security

#### Passwords
- Bafser’s `UserBase` uses bcrypt for password hashing. Never store plain‑text passwords.
- When creating users programmatically, use `User.new(...)` which hashes the password automatically.
- Change the default admin password (`admin`/`admin`) in production—the framework forces a random password if it detects the default.

#### JWT Tokens
- Tokens are stored in HTTP‑only cookies, which mitigates XSS attacks.
- Set `JWT_ACCESS_TOKEN_EXPIRES` to a reasonable duration (e.g., 24 hours).
- Use `JWT_ACCESS_TOKEN_REFRESH` to automatically refresh tokens before they expire, providing a seamless user experience.

#### Permission Checks
- Use the built‑in permission system via `User.has_operation` to verify that the current user has the required operation before performing sensitive actions.
- Define fine‑grained operations in `_operations.py` and assign them to roles in `_roles.py`.
- Avoid hard‑coding role IDs; use the constants defined in your `Roles` class.

#### Input Validation
- Use `get_json_values` or `get_json_values_from_req` for every endpoint that accepts JSON.
- Specify the expected type for each field; the function will return a descriptive error if validation fails.
- Never trust data from the client, even for internal APIs.

### 5.3 Database Performance

#### Session Management
- Bafser provides a request‑scoped database session via `get_db_session()`.
- Use `use_db_session` decorator for functions that need a session but aren’t Flask routes.
- Never share a session across threads; the framework already handles this correctly.

#### Query Patterns
- Use the mixin methods (`get2`, `all2`, `query2`) for convenience, but be aware they fetch the session from the global context. In background tasks, explicitly pass a session.
- For complex queries, write raw SQLAlchemy queries but keep them inside model class methods (e.g., `Task.get_by_user`).
- Leverage `ObjMixin`’s soft‑delete: always consider whether you need `includeDeleted=True`.

#### Indexes
- Add SQLAlchemy `index=True` to columns frequently used in `WHERE` or `JOIN` clauses.
- The `BigIdMixin`’s `id_big` column already has an index.

### 5.4 Logging and Monitoring

#### What to Log
- Use `get_logger_frontend()` for client‑side errors and analytics.
- Use `Log` model (audit log) for all data changes (created, updated, deleted, restored). The `ObjMixin` automatically creates `Log` entries.

#### Dashboards
- Expose the built‑in dashboard (`/dashboard`) only to internal networks or protect it with a strong permission.
- Consider exporting dashboard CSV data to a monitoring system (Prometheus, Grafana) for long‑term trends.

### 5.5 Testing

#### Unit Tests
- Use `pytest` with a test‑specific SQLite database.
- Override `bafser_config` in your test setup to point to a temporary database file.
- Use `bafser.utils.override_get_db_session` to inject a test session.

#### Integration Tests
- Start the actual Flask app in test mode (`DEV_MODE=True`) and use the `test_client`.
- The `DELAY_MODE` setting can be used to simulate network latency for UI testing.

#### Testing Authentication
- The `protected_route` decorator relies on JWT cookies. In tests, you can manually set the cookie after logging in via a test endpoint.
- Use `bafser.scripts.add_user` to create test users with specific roles.

### 5.6 Deployment

#### Configuration Management
- Store secrets in environment variables and load them with `AppConfig.add_secret_key_env`.
- Use different `bafser_config.py` files for each environment (e.g., via symlinks) or override settings with environment variables (the `ENV:DBPATH` pattern).

#### Database Migrations
- Enable `use_alembic = True` in production.
- Run `bafser alembic upgrade` as part of your deployment script before starting the server.
- In a multi‑pod setup, ensure only one pod runs migrations (use the `--setup` flag with `THREADED=True`).

#### WSGI Server
- Use Gunicorn (or uWSGI) with multiple workers. Bafser’s `THREADED=True` mode is designed for such environments.
- Set `THREADED = True` in production to disable file‑based log rotation and enable session‑pool optimizations.

#### Health Checks
- Enable `HEALTH_ROUTE = True` to expose `/api/health`. Use this endpoint for load‑balancer health checks.
- The health endpoint tests database connectivity; add any additional checks your app needs.

### 5.7 Maintaining Extensibility

#### Subclassing Base Classes
- When extending `UserBase`, `Image`, or other core models, follow the override pattern shown in the documentation (use `@override` and call `super()`).
- Keep your extensions in the `data/` folder; the framework will pick them up automatically.

#### Adding New Blueprints
- Place new blueprints in the `blueprints/` folder. They will be auto‑discovered.
- If you need a different folder, change `blueprints_folder` in `bafser_config.py`.

#### Custom Log Handlers
- Use `add_logger` and `create_log_handler` to add dedicated logs for business events (e.g., payment processing, user activity).
- Follow the same CSV format for consistency, or switch to JSON if you use a log aggregator.

### 5.8 Common Pitfalls

#### Circular Imports
- Because models are imported dynamically, avoid importing blueprints inside model files.
- Use local imports inside functions if you need to reference a model from another model.

#### JWT Identity Changes
- The JWT identity includes a hash of the user’s password. If the password changes, existing tokens become invalid (by design).
- Inform users they will be logged out after a password change.

#### Soft‑Delete and Unique Constraints
- Adding `unique=True` to a column while using `ObjMixin` can cause conflicts with deleted rows. Consider adding a partial index that excludes deleted rows, or use a composite unique constraint with `deleted`.

### 5.9 Performance Tuning

#### Database Connection Pool
- The default pool size is 5 with max overflow 10. Adjust these values in `db_session.py` if your application handles high concurrency.
- For MySQL, ensure `wait_timeout` is greater than `pool_recycle` (default 3600 seconds).

#### Caching Static Assets
- The `STATIC_FOLDERS` list determines which paths get long‑term cache headers. Add your front‑end asset paths here.
- Use `CACHE_MAX_AGE` to control how long browsers cache static files.

By following these practices, you’ll build applications that are secure, maintainable, and ready to scale.
