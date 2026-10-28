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

#### Public API errors

Raise `PublicError` only when its message is safe to show to API clients:

```py
from bafser import PublicError

raise PublicError("Please select an available ticket type")  # HTTP 400
raise PublicError("This action is not allowed", status=403)
raise PublicError("Limit reached", status=409, code="limit_reached", details={"remaining": 0})
```

Subclasses can override `status` (400 by default), `code` and `details`;
`get_dict()` includes only `msg` and the optional public metadata.
Omitted `code`/`details` or explicit `Undefined` preserve subclass defaults;
passing `None` explicitly clears them. Constructor arguments can override all
public fields. 
`JsonParseError` also inherits `PublicError`. API handlers may expose messages
from this hierarchy or return explicitly chosen text through `response_msg`.
Other exceptions return `Internal Server Error` with HTTP 500, including in
development mode; their text, attributes and chained causes remain server-side.
Failed public and unexpected requests roll back the request session before
returning a response. Do not catch arbitrary `ValueError` or `PermissionError`
and return their text to clients.

#### UTC dates

`get_datetime_utc()` returns the current instant as a timezone-aware UTC datetime.
It is exported from both `bafser` and `bafser.utils`.

Set `datetime_utc = True` in `bafser_config.py` to use UTC for shared model
timestamps and file logs. In this mode `get_datetime_now()` delegates to the UTC
clock, `parse_datetime()` converts ISO offsets to UTC (naive input is already UTC),
and model serialization includes a `Z` suffix. SQL `DATETIME` values store UTC
without a timezone; convert existing local timestamps before enabling this mode.
Without this setting the legacy behavior is preserved.

`parse_date()` returns a `datetime.date` from an ISO date or datetime string.
It discards the time and offset without shifting the written calendar day,
independently of `datetime_utc`. Both parsers return `None` for invalid input.

#### Normalized search columns

`normalized_column` declares a stored string derived from a referenced field:

```py
from functools import partial
from sqlalchemy import Index
from sqlalchemy.orm import Mapped, mapped_column
from bafser import SqlAlchemyBase, ObjMixin, TruncateString, normalized_column, normalize_search

human_search = normalize_search

class Person(SqlAlchemyBase, ObjMixin):
    __tablename__ = "Person"
    name: Mapped[str] = mapped_column(TruncateString(128))
    name_search: Mapped[str] = normalized_column(
        name, normalizer=human_search,
    )

Index("ix_person_name_search", Person.name_search, mysql_length=256)

person = Person(name="  ЁЛКА  ")
assert person.name == "  ЁЛКА  "
assert person.name_search == "elka"
person.name = "  НОВОЕ ИМЯ "
assert person.name_search == "novoe imya"
```

Without `length`, the derived column is `Text`: the full normalized result is
stored without a helper-imposed length limit. Database type limits still apply.
The index above uses a 256-character prefix on MySQL and a normal index on SQLite;
the data itself is never cut to the index prefix. For a MySQL `Text` column, use
an explicit `Index(..., mysql_length=...)` instead of a plain `index=True`.

With `length=N`, the derived column is `String(N)` and `overflow` controls what
happens when normalization expands the value past that limit:

| Declaration | Overflow behavior |
| --- | --- |
| `normalized_column(name)` | Full result in `Text`; `overflow` has no effect |
| `normalized_column(name, length=256)` | `truncate` for a `TruncateString` source, otherwise `raise` |
| `normalized_column(name, length=256, overflow="truncate")` | Always keep the first 256 normalized characters |
| `normalized_column(name, length=256, overflow="raise")` | Always raise `NormalizedValueTooLongError` on overflow |

For a column with an explicit length limit, `index=True` creates a normal index:

```py
name_search: Mapped[str] = normalized_column(
    name, length=256, index=True,
)
```

One model can have multiple normalized columns, including several with different
normalizers for the same source and columns derived from different sources.
Each field uses its own normalizer and overflow policy.

Truncation occurs in the helper before assignment and SQL, so Python and stored
values agree. It deliberately drops the searchable tail: a full query longer than
the stored result may not match. Choose `Text` when the complete search value is
required. Explicit `overflow` overrides the source-dependent default.

Declare the source above the helper with `mapped_column`, not just an annotation.
String names, SQL expressions, relationships and fields of unrelated models are
rejected. Database column names may differ from Python attribute names. Copied
mixin fields are supported. For inherited sources, use `declared_attr`; stacking
`classmethod` also gives type checkers the correct type for `cls`:

```py
@declared_attr
@classmethod
def name_search(cls) -> Mapped[str]:
    return normalized_column(cls.name, length=256, normalizer=human_search)
```

Derived columns have `init=False`, so constructors do not accept their values.
Nullability follows the source; an explicit `nullable` option must match it.
Annotate nullable fields as `Mapped[str | None]`. `None` is preserved without
calling the normalizer; empty strings remain strings. Derived fields are ordinary
mapped columns for serialization; use your model's `serialize_rules` if needed.

Assignment listeners run after standard `@validates` handlers. `before_flush`
recomputes new/changed values from the final source, repairing manual edits to the
derived field and covering later custom assignment handlers. Unrelated changes
do not load deferred sources or recompute search strings. Loading an existing
object does not silently rewrite its stored search data.

`normalize_search(text, *, replace_yo=True, strip_diacritics=True,
strip_punctuation=True, cyrillic_to_latin=True, transliterate=None)` applies NFKC,
casefold, ё/diacritic folding, punctuation replacement and whitespace collapse.
Punctuation becomes spaces, preserving word boundaries. Diacritic removal also
changes Cyrillic `й` to `и`. Pass the corresponding options as `False` to preserve
these distinctions; preserving `ё` needs both `replace_yo=False` and
`strip_diacritics=False`.

Built-in Russian-to-Latin transliteration is enabled by default and runs after
ё/diacritic folding: `ж -> zh`, `х -> h`, `ц -> ts`, `щ -> sch`, `ю -> yu`,
`я -> ya`; `ь` and `ъ` are removed. Other characters, including Latin text and
letters outside the Russian alphabet, are preserved. With default folding,
`ё -> е -> e` and `й -> и -> i`; disabling folding permits `ё -> yo`, `й -> y`.
Pass `cyrillic_to_latin=False` to preserve Cyrillic after folding.

```py
assert normalize_search("Яна, Ёлка!") == "yana elka"
cyrillic_search = partial(normalize_search, cyrillic_to_latin=False)
assert cyrillic_search("Яна, Ёлка!") == "яна елка"
```

The existing callable `transliterate` remains available for custom rules. It
receives NFKC/casefold text before the other transforms and must return a string.
Custom column normalizers must be pure, deterministic `str -> str` callables;
reuse the same callable and settings for search input:

```py
query = Person.query().filter(
    Person.name_search.contains(human_search(search_text), autoescape=True)
)
```

`autoescape=True` treats remaining `%` and `_` literally. To preserve punctuation
in both stored values and queries, set `strip_punctuation=False` in their shared
normalizer. Handle empty normalized queries before filtering: punctuation-only
input now becomes empty. A normal B-tree index helps equality
and suitable prefix queries; it does not provide efficient arbitrary substring
search. The derived length is explicit because casefold/transliteration can expand
text. Fixed-length columns use the overflow policy described above.
Invalid values/normalizer failures raise `NormalizationError` with model and
field context. `TruncateString` sources are normalized from `prepare_value()` —
the portion actually stored — while the original Python attribute is unchanged.
Ordinary SQLAlchemy string types and `TruncateString` are supported; other bind
processors, computed/onupdate sources and chains of derived columns are rejected.
The source must have a concrete Python value when saving; an omitted server
default cannot be normalized before its INSERT. This also applies to `None` when
SQLAlchemy would omit it and invoke an INSERT default; supply a concrete string
or use a source type configured to persist `None` explicitly.

Bulk UPDATE and direct SQL bypass attribute/flush synchronization. Prepare both
values explicitly for ORM bulk writes:

```py
from sqlalchemy import update
from bafser import normalized_update_values

values = normalized_update_values(Person, name="Новое имя")
session.execute(update(Person).where(Person.id == person_id).values(**values))
```

The helper accepts Python attribute names and concrete values, adds all affected
derived fields, and rejects SQL expressions and explicit derived values. It does
not execute SQL. For guarantees across independent SQL writers, use a database
generated column or trigger with a database-specific normalization expression.
Python normalizers are not automatically translated to SQL.

For existing rows or an algorithm/Unicode-data change:

```py
from bafser import rebuild_normalized_columns
from sqlalchemy.orm import Session

with Session(engine) as session:
    count = rebuild_normalized_columns(Person, db_sess=session, batch_size=500)
    session.commit()
```

This returns the number of processed rows, includes soft-deleted records, supports
composite primary keys, and pages by primary key without an open streaming cursor.
It flushes the supplied session (including its existing changes), never commits or
closes it, and refreshes database values after flushing. Use a dedicated maintenance
session; rollback can undo the whole rebuild. For a new column: add it nullable,
deploy compatible writers, backfill, then enforce the final nullability/index.
Stop old writers during the transition so they cannot reintroduce stale values.
Adding the helper to a model alone does not migrate existing database tables.

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
executes unless emulation is enabled. `allow_unsupported_for_update_clause`
defaults to `None`: `create_app` resolves it to `AppConfig.DEV_MODE`, enabling
emulation in development and keeping strict checks in production. Before
`create_app`, `None` or a missing setting keeps strict checks. Explicit `True`
or `False` overrides the automatic choice. For test runs without row-lock support:

```py
# bafser_config.py — test configuration only
allow_unsupported_for_update_clause = True
```

This refreshes the objects and emulates transaction-scoped marks, so model checks
still work. An ordinary query without `for_update=True` still fails the check.
In this mode, `is_for_update=True` does not prove a real row lock exists. Test
concurrent access on MySQL, not SQLite. The setting never suppresses database
errors such as deadlocks or lock timeouts.
