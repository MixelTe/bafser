import os

from bafser.scripts import alembic_init
import bafser_config


def init_project():
    r = input("Do you want to change bafser_config? [Y/n]: ")
    if r != "n":
        print("Run again when bafser_config is ready")
        return
    os.makedirs(bafser_config.data_tables_folder, exist_ok=True)
    write_file(os.path.join(bafser_config.data_tables_folder, "__init__.py"), data__init__)
    write_file(os.path.join(bafser_config.data_tables_folder, "_operations.py"), data_operations)
    write_file(os.path.join(bafser_config.data_tables_folder, "_roles.py"), data_roles)
    write_file(os.path.join(bafser_config.data_tables_folder, "_tables.py"), data_tables)
    write_file(os.path.join(bafser_config.data_tables_folder, "user.py"), data_user)
    os.makedirs(bafser_config.blueprints_folder, exist_ok=True)
    write_file(os.path.join(bafser_config.blueprints_folder, "docs.py"), blueprints_docs_py)
    write_file("main.py", main)
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
        ])
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
# from test.data._operations import Operations


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
data_user = """
from bafser import UserBase


class User(UserBase):
    def __repr__(self):
        return f"<{self.__class__.__name__}> [{self.id}] {self.login}"
"""

blueprints_docs_py = """from flask import Blueprint


blueprint = Blueprint("docs", __name__)


@blueprint.route("/api")
def docs():
    return {
        "/api": {
            "__desc__": "Api docs",
            "request": "",
            "response": "",
        },
    }
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

gitignore_base = """.venv/
__pycache__/
build/
dist/"""
