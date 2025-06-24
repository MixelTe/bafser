# base for flask server by Mixel Te

## requirements.txt
Python 3.9.5
```
flask==2.1.2
sqlalchemy==2.0.19
werkzeug==2.3.6
sqlalchemy_serializer==1.4.1
pyjwt<2.10
flask_jwt_extended==4.5.2
PyMySQL==1.1.1
```

## usage
scripts: `python -m bafser`

copy `bafser_config.example.py` to project root as `bafser_config.py`

create files:

.gitignore
```
.venv
*__pycache__*
logs/
db/
/images
/fonts
secret_key_jwt.txt
```

```py
# data/_operations.py
from bfs import OperationsBase


class Operations(OperationsBase):
    oper_id = ("oper_id", "Operation description")
    oper_id2 = ("oper_id2", "Operation description")
    ...
```
```py
# data/_roles.py
from bfs import RolesBase
from data._operations import Operations


class Roles(RolesBase):
    role_name = 2
    role_name2 = 3
    ...


Roles.ROLES = {
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
from bfs import TablesBase


class Tables(TablesBase):
    TableName = "TableName"
    AnotherTableName = "AnotherTableName"
```
```py
# data/some_table.py
from bfs import SqlAlchemyBase, ObjMixin
from data._tables import Tables


class SomeTable(SqlAlchemyBase, ObjMixin):
    __tablename__ = Tables.SomeTable
    ...

```
* `IdMixin` adds `id` column
* `ObjMixin` adds `id` and `deleted` columns
* `SingletonMixin` adds `id` column

```py
# main.py
import sys
from bfs import AppConfig, create_app
from scripts.init_dev_values import init_dev_values


app, run = create_app(__name__, AppConfig(
    MESSAGE_TO_FRONTEND="",
    DEV_MODE="dev" in sys.argv,
    DELAY_MODE="delay" in sys.argv,
)
    .add_data_folder("FONTS_FOLDER", "fonts")
    .add_secret_key("API_SECRET_KEY", "secret_key_api.txt")
)

run(__name__ == "__main__", lambda: init_dev_values(True), port=5001)
```

### modifying User and Image
User:
```py
from sqlalchemy import Column, String
from sqlalchemy.orm import Session

from bfs import UserBase
from data._roles import Roles


class User(UserBase):
    newColumn = Column(String)

    @classmethod
    def new(cls, creator: "User", login: str, password: str, name: str, roles: list[int], newColumn: str, db_sess: Session = None) -> "User":
        return super().new(creator, login, password, name, roles, db_sess, newColumn=newColumn)

    @staticmethod
    def _new(db_sess: Session, user_kwargs: dict, newColumn: str):
        user = User(**user_kwargs, newColumn=newColumn)
        changes = [("newColumn", newColumn)]
        return user, changes

    @staticmethod
    def create_admin(db_sess: Session):
        fake_creator = User.get_fake_system()
        return User.new(fake_creator, "admin", "admin", "Админ", [Roles.admin], "newColumnValue", db_sess=db_sess)

```
Image:
```py
# to use relationship you must name the file something other than image.py
# img.py for the example, because of the way sqlalchemy finds classes
image = orm.relationship("data.img.Image")
```
```py
from typing import TypedDict, Union
from sqlalchemy import Column, String

from bfs import Image as ImageBase, get_json_values
from data.user import User


class ImageJson(TypedDict):
    data: str
    name: str
    newColumnData: str


TError = str


class Image(ImageBase):
    newColumn = Column(String)

    @classmethod
    def new(cls, creator: User, json: ImageJson) -> Union[tuple[None, TError], tuple["Image", None]]:
        return super().new(creator, json)

    @staticmethod
    def _new(creator: User, json: ImageJson, image_kwargs):
        newColumnData, values_error = get_json_values(json, ("newColumnData", None))
        if values_error:
            return None, None, values_error

        img = Image(**image_kwargs, newColumn=newColumnData)
        changes = [("newColumn", newColumnData)]
        return img, changes, None
```

#### csv header for requests log
```csv
reqid;ip;uid;asctime;method;url;level;message;code;json
```