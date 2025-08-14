# base for flask server by Mixel Te

## dependencies
Python 3.12
```
alembic == 1.16.4
flask == 3.1.1
flask_jwt_extended == 4.7.1
PyMySQL == 1.1.1
sqlalchemy == 2.0.29
sqlalchemy_serializer == 1.4.22
werkzeug == 3.1.3
```

## usage
scripts: `bafser`

init project: `bafser init_project`

---
or manually

copy `bafser_config.example.py` to project root as `bafser_config.py`

init alimbic `bafser alimbic init`

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

Mixins add `get` methods also

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
from typing import Any, override
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
        user = User(**user_kwargs, newColumn=newColumn)
        changes = [("newColumn", newColumn)]
        return user, changes

    @classmethod
    @override
    def create_admin(cls, db_sess: Session):
        fake_creator = User.get_fake_system()
        return User.new(fake_creator, "admin", "admin", "Admin", [Roles.admin], "newColumnValue", db_sess=db_sess)

```
Image:
```py
from typing import TypedDict, override
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