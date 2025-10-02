import os
import uuid
from typing import cast

import bafser_config
from bafser.scripts import alembic_init


def init_project():
    r = input("Do you want to change bafser_config? [Y/n]: ")
    if r != "n":
        print("Run again when bafser_config is ready")
        return
    with_tgapi = False
    try:
        import bafser_tgapi  # type: ignore
        with_tgapi = True
    except Exception:
        pass
    os.makedirs(bafser_config.data_tables_folder, exist_ok=True)
    write_file(os.path.join(bafser_config.data_tables_folder, "__init__.py"), data__init__)
    write_file(os.path.join(bafser_config.data_tables_folder, "_operations.py"), data_operations)
    write_file(os.path.join(bafser_config.data_tables_folder, "_roles.py"), data_roles)
    write_file(os.path.join(bafser_config.data_tables_folder, "_tables.py"), data_tables_tgapi if with_tgapi else data_tables)
    write_file(os.path.join(bafser_config.data_tables_folder, "user.py"), data_user_tgapi if with_tgapi else data_user)
    if not with_tgapi:
        os.makedirs(bafser_config.blueprints_folder, exist_ok=True)
        write_file(os.path.join(bafser_config.blueprints_folder, "docs.py"), blueprints_docs_py)
    if with_tgapi:
        bot_folder = cast(str, bafser_config.bot_folder)  # type: ignore
        config_dev_path = cast(str, bafser_config.config_dev_path)  # type: ignore
        os.makedirs(bot_folder, exist_ok=True)
        write_file(os.path.join(bot_folder, "bot.py"), tgapi_bot_py)
        write_file(config_dev_path, tgapi_config_dev)
        write_file(os.path.join(bafser_config.data_tables_folder, "msg.py"), tgapi_data_msg)
    write_file("main.py", main_tgapi if with_tgapi else main)
    if not os.path.exists(".gitignore"):
        gitignore = gitignore_base
        gitignore += "\n" + "\n".join([
            bafser_config.db_dev_path,
            bafser_config.log_info_path,
            bafser_config.log_requests_path,
            bafser_config.log_errors_path,
            bafser_config.log_frontend_path,
            bafser_config.jwt_key_file_path,
            bafser_config.images_folder if bafser_config.images_folder[-1] == "/" else bafser_config.images_folder + "/",
        ] + ([
            cast(str, bafser_config.log_bot_path),  # type: ignore
            cast(str, bafser_config.config_path),  # type: ignore
            cast(str, bafser_config.config_dev_path),  # type: ignore
        ] if with_tgapi else []))
        write_file(".gitignore", gitignore)
    if bafser_config.use_alembic:
        alembic_init()


def write_file(path: str, text: str):
    with open(path, "w", encoding="utf8") as f:
        f.write(text)


def run(args: list[str]):
    init_project()


data__init__ = """from ._operations import Operations
from ._roles import Roles
from ._tables import Tables

__all__ = [
    "Operations",
    "Roles",
    "Tables",
]
"""
data_operations = """from bafser import OperationsBase


class Operations(OperationsBase):
    pass
"""
data_roles = """from bafser import RolesBase
# from data import Operations


class Roles(RolesBase):
    user = 2


Roles.ROLES = {
    Roles.user: {
        "name": "User",
        "operations": []
    },
}
"""
data_tables = """from bafser import TablesBase


class Tables(TablesBase):
    pass
"""
data_tables_tgapi = """from bafser import TablesBase


class Tables(TablesBase):
    Msg = "Msg"
"""
data_user = """from bafser import UserBase


class User(UserBase):
    def __repr__(self):
        return f"<{self.__class__.__name__}> [{self.id}] {self.login}"
"""
data_user_tgapi = """from bafser_tgapi import TgUserBase

from data import Roles


class User(TgUserBase):
    _default_role = Roles.user
"""

blueprints_docs_py = """from flask import Blueprint
from bafser import get_api_docs


blueprint = Blueprint("docs", __name__)


@blueprint.route("/api")
def docs():
    return get_api_docs()
"""

main = """import sys
from bafser import AppConfig, create_app


app, run = create_app(__name__, AppConfig(
    MESSAGE_TO_FRONTEND="",
    DEV_MODE="dev" in sys.argv,
    DELAY_MODE="delay" in sys.argv,
))

run(__name__ == "__main__")
"""
main_tgapi = """import sys

import bafser_tgapi as tgapi
from bafser import AppConfig, create_app

from bot.bot import Bot

app, run = create_app(__name__, AppConfig(DEV_MODE="dev" in sys.argv))
tgapi.setup(botCls=Bot, app=app)

DEVSERVER = "devServer" in sys.argv
if DEVSERVER:
    tgapi.set_webhook()
run(DEVSERVER)

if not DEVSERVER:
    if __name__ == "__main__":
        tgapi.run_long_polling()
    else:
        tgapi.set_webhook()

"""

gitignore_base = """.venv/
__pycache__/
build/
dist/"""

tgapi_bot_py = """import bafser_tgapi as tgapi

from data.user import User


class Bot(tgapi.BotWithDB[User]):
    _userCls = User
"""
tgapi_config_dev = f"""bot_token = 1234567890:AAAAAAAAAA_AAAAAAAAA_AAAAAAAAAAAAAA
bot_name = @Bot
webhook_token = {uuid.uuid4()}
url = https://example.com/
"""
tgapi_data_msg = """from bafser_tgapi import MsgBase

from data import Tables


class Msg(MsgBase):
    __tablename__ = Tables.Msg
"""
