# base for flask server by Mixel Te

## dependencies
Python 3.10 or later
```
alembic >= 1.16.4, < 2
cryptography >= 46.0.5, < 51
concurrent-log-handler >= 0.9.28, < 1
flask >= 3.1.1, < 4
flask_jwt_extended >= 4.7.1, < 5
PyJWT >= 2.0, < 3.0
PyMySQL >= 1.1.1, < 2
python-dotenv >= 1.0, < 2
sqlalchemy >= 2.0.45, < 2.1
sqlalchemy_serializer >= 1.5.5, < 2
typing_extensions >= 4.13.2, < 5
werkzeug >= 3.1.3, < 4
```

## usage
scripts: `bafser`

Both `bafser` and `python -m bafser` load `.env` from the current working
directory before running a command. Existing environment variables take
precedence; a missing `.env` is allowed. Parent directories are not searched.
For example, `DBPATH` in `.env` supplies a configuration value declared as
`db_path = "ENV:DBPATH"`. This loading applies to CLI commands; application
entry points must load their own `.env` if needed.

init project: `bafser init_project` (existing generated files are kept; use `--force` to replace them)

With `use_alembic = True`, create an initial migration before starting the app:
`bafser alembic revision` followed by `bafser alembic upgrade`.

run `gunicorn -w 4 --threads 2 --worker-class gthread -b 0.0.0.0:80 main:app`

---
or manually

copy `bafser_config.example.py` to project root as `bafser_config.py`

init alembic `bafser alembic init` (existing templates are kept; use `--force` to replace them)

### create files:

.gitignore
```
.venv
*__pycache__*
/logs
/db
/images
/fonts
secret_key_jwt.txt
```

```py
# data/_operations.py
from bafser import OperationsBase


class Operations(OperationsBase):
    oper_id = ("oper_id", "Operation description")
    oper_id2 = ("oper_id2", "Operation description")
    ...
```
```py
# data/_roles.py
from bafser import RolesBase
from data._operations import Operations


class Roles(RolesBase):
    # admin = 1 is already set for admin role
    role_name = 2
    role_name2 = 3
    ...


Roles.ROLES = {
    # Roles.admin: {"name": "Admin", "operations": []} = 1 is auto created with all Operations
    Roles.role_name: {
        "name": "Role name",
        "operations": [
            Operations.oper_id,
            Operations.oper_id2,
        ]
    },
    Roles.role_name2: {
        "name": "Role name 2",
        "operations": [
            Operations.oper_id,
        ]
    },
}
```
```py
# data/_tables.py
from bafser import TablesBase


class Tables(TablesBase):
    TableName = "TableName"
    AnotherTableName = "AnotherTableName"
```
```py
# data/user.py
from bafser import UserBase


class User(UserBase):
    def __repr__(self):
        return f"<{self.__class__.__name__}> [{self.id}] {self.login}"
```
```py
# data/some_table.py
from bafser import SqlAlchemyBase, ObjMixin
from data._tables import Tables


class SomeTable(SqlAlchemyBase, ObjMixin):
    __tablename__ = Tables.SomeTable
    ...

```
* `IdMixin` adds `id` column
* `ObjMixin` adds `id` and `deleted` columns
* `SingletonMixin` adds `id` column

Mixins also provide `get`, `query`, and `all`. They use the request session by
default; pass `db_sess` when working outside a request or within a specific
transaction:

```py
item = SomeTable.get(item_id)
item = SomeTable.get(item_id, db_sess=session, for_update=True)
items = SomeTable.all(db_sess=session)
```

```py
# main.py
import sys
from bafser import AppConfig, create_app
from scripts.init_dev_values import init_dev_values


app, run = create_app(__name__, AppConfig(
    MESSAGE_TO_FRONTEND="",
    DEV_MODE="dev" in sys.argv,
    DELAY_MODE="delay" in sys.argv,
)
    .add_data_folder("FONTS_FOLDER", "fonts")
    .add_secret_key("API_SECRET_KEY", "secret_key_api.txt")
)

run(__name__ == "__main__", None, init_dev_values)
```

### modifying User and Image
User:
```py
from typing import Any
from typing_extensions import override
from sqlalchemy.orm import Session, Mapped, mapped_column
from bafser import UserBase, UserKwargs

from data._roles import Roles


class User(UserBase):
    newColumn: Mapped[str]

    @classmethod
    @override
    def new(cls, creator: UserBase, login: str, password: str, name: str, roles: list[int], newColumn: str, *, db_sess: Session | None = None):
        return super().new(creator, login, password, name, roles, db_sess=db_sess, newColumn=newColumn)

    @classmethod
    @override
    def _new(cls, db_sess: Session, user_kwargs: UserKwargs, *, newColumn: str, **kwargs: Any):
        return User(**user_kwargs, newColumn=newColumn)

    @classmethod
    @override
    def create_admin(cls, db_sess: Session):
        fake_creator = User.get_fake_system()
        return User.new(fake_creator, "admin", "admin", "Admin", [Roles.admin], "newColumnValue", db_sess=db_sess)

```
Image:
```py
from typing import TypedDict
from typing_extensions import override
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from bafser import Image as ImageBase, ImageKwargs, get_json_values
from test.data.user import User


class ImageJson(TypedDict):
    data: str
    name: str
    newColumnData: str


class Img(ImageBase):
    newColumn: Mapped[str]

    @classmethod
    @override
    def new(cls, creator: User, json: ImageJson):  # type: ignore
        return super().new(creator, json)

    @classmethod
    @override
    def _new(cls, creator: User, json: ImageJson, image_kwargs: ImageKwargs):  # type: ignore
        newColumnData, values_error = get_json_values(json, ("newColumnData", str))
        if values_error:
            return None, None, values_error
        img = Img(**image_kwargs, newColumn=newColumnData)
        changes = [("newColumn", newColumn)]
        return img, changes, None

```

#### csv header for requests log
```csv
reqid;ip;uid;asctime;method;url;message;code;json
```

#### UTC dates

`get_datetime_utc()` returns the current instant as a timezone-aware UTC datetime.
It is exported from both `bafser` and `bafser.utils`.

Set `datetime_utc = True` in `bafser_config.py` to use UTC for shared model
timestamps and file logs. In this mode `get_datetime_now()` delegates to the UTC
clock, `parse_date()` converts ISO offsets to UTC (naive input is already UTC),
and model serialization includes a `Z` suffix. SQL `DATETIME` values store UTC
without a timezone; convert existing local timestamps before enabling this mode.
Without this setting the legacy behavior is preserved.

#### FOR UPDATE

`for_update=True` locks and refreshes matching rows, including instances already
loaded in the session. `item.is_for_update` is a read-only, transaction-scoped
mark; `item.require_for_update()` raises `ForUpdateRequiredError` if it is absent.
Neither operation acquires a lock:

```py
class Account(SqlAlchemyBase, ObjMixin):
    # ... mapped fields ...
    def withdraw(self, amount: int):
        self.require_for_update()
        # Check the current balance, then change it.

account = Account.get(account_id, for_update=True, db_sess=session)
if account is not None:
    account.withdraw(amount)
session.commit()
```

Obtain the lock before reading values used for a decision or changing the object.
The query uses SQLAlchemy's normal autoflush: pending changes can be written before
the locking SELECT. With autoflush disabled, refreshing can discard pending changes.

Tracking covers `query/get/all(for_update=True)` and helpers built on them,
including both `get_by_big_id` paths. Merely constructing a query does not mark
anything. Marks are assigned only after successful query/result loading, to
explicitly selected instances of the helper's model. Relationships are not marked
automatically, even if eager loading also causes their rows to be locked.
Scalar projections and direct SQLAlchemy queries are not tracked. The results of
tracked entity queries are buffered before they are returned, including iteration;
do not use them for unbounded streaming. Keep the exclusive FOR UPDATE clause
unmodified; shared locks and `of=` overrides are not supported by tracking.

Marks expire after commit, rollback, session close or object detachment. Rolling
back a SAVEPOINT conservatively invalidates all marks in that session; releasing
a SAVEPOINT preserves marks. Failed SQLAlchemy session statements also invalidate
marks, since a database deadlock can implicitly roll back the transaction.
The mark is not a database column or a serialized
field. It records the bafser protocol, not every possible database lock.
Use ordinary session-owned transactions, transactional tables (InnoDB on MySQL),
and no DBAPI autocommit or externally managed transaction boundaries.

Supported database dialects are MySQL/MariaDB, PostgreSQL and Oracle. Other
dialects, including SQLite, raise `LockNotSupportedError` when a tracked query
executes. For test runs without row-lock support, explicitly configure:

```py
# bafser_config.py — test configuration only
allow_unsupported_for_update_clause = True  # default: False
```

This refreshes the objects and emulates transaction-scoped marks, so model checks
still work. An ordinary query without `for_update=True` still fails the check.
In this mode, `is_for_update=True` does not prove a real row lock exists. Test
concurrent access on MySQL, not SQLite. The setting never suppresses database
errors such as deadlocks or lock timeouts.
