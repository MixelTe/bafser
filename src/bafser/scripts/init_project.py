import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import cast

from bafser_cli import parse_init_project_args

from ..validate_config import validate_config
from .alembic import init as init_migrations


def _read_project_config(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("_bafser_project_setup_config", path)
    if spec is None or spec.loader is None:
        raise ImportError("Could not load project configuration")
    config = importlib.util.module_from_spec(spec)
    previous_import_path = sys.path.copy()
    previous_module_entry = {spec.name: sys.modules[spec.name]} if spec.name in sys.modules else {}
    sys.path.insert(0, str(path.resolve().parent))
    # Annotation-aware decorators need their module registered during execution.
    sys.modules[spec.name] = config
    try:
        spec.loader.exec_module(config)
        validate_config(config)
        return config
    finally:
        sys.path[:] = previous_import_path
        sys.modules.pop(spec.name, None)
        sys.modules.update(previous_module_entry)


def _package_directory(root: Path, name: str) -> Path:
    directory = root
    parts = name.split(".")
    for part in parts:
        directory /= part
        directory.mkdir(exist_ok=True)
        # Parent package files must never be overwritten by --force.
        if directory != root.joinpath(*parts):
            write_file(str(directory / "__init__.py"), "")
    return directory


def _gitignore_entry(root: Path, path: str) -> str | None:
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        return None
    entry = "/" + resolved.relative_to(root).as_posix()
    return entry + "/" if path.endswith(("/", "\\")) else entry


def init_project(force: bool = False, *, directory: str | Path | None = None):
    root = Path(directory).resolve() if directory is not None else Path.cwd()
    root.mkdir(parents=True, exist_ok=True)
    config_path = root / "bafser_config.py"
    if not config_path.exists():
        template = Path(__file__).resolve().parents[1] / "bafser_config.example.py"
        source = template.read_text(encoding="utf8")
        if importlib.util.find_spec("bafser_tgapi") is not None:
            tgapi_source = template.with_name("bafser_config.tgapi.py").read_text(encoding="utf8")
            # Reuse the base config's imports and path anchors in the combined file.
            source += "\n" + tgapi_source[tgapi_source.index("# ---------- tgapi ----------") :]
        write_file(str(config_path), source)
        print(f"Created {config_path}; review its settings, then run init_project again")
        return
    config = _read_project_config(config_path)
    r = input("Do you want to change bafser_config? [Y/n]: ")
    if r != "n":
        print("Run again when bafser_config is ready")
        return
    with_tgapi = importlib.util.find_spec("bafser_tgapi") is not None

    def write(path: str | Path, text: str) -> None:
        write_file(str(root / path), text, force=force)

    tables_name = config.data_tables_package
    tables = None
    if tables_name is not None:
        tables = _package_directory(root, tables_name)
        write(tables / "__init__.py", data__init__)
        write(tables / "_operations.py", data_operations)
        write(tables / "_roles.py", data_roles.replace("from data", f"from {tables_name}"))
        write(tables / "_tables.py", data_tables_tgapi if with_tgapi else data_tables)
        write(tables / "user.py", (data_user_tgapi if with_tgapi else data_user).replace("from data", f"from {tables_name}"))
    if not with_tgapi and config.blueprints_package is not None:
        blueprints = _package_directory(root, config.blueprints_package)
        write(blueprints / "__init__.py", "")
        write(blueprints / "docs.py", blueprints_docs_py)
    if with_tgapi:
        if tables_name is None or tables is None:
            raise ValueError("Telegram project setup requires data_tables_package")
        bot_folder = root / cast(str, config.bot_folder)
        config_dev_path = root / cast(str, config.config_dev_path)
        bot_folder.mkdir(parents=True, exist_ok=True)
        write(bot_folder / "bot.py", tgapi_bot_py.replace("from data", f"from {tables_name}"))
        write(config_dev_path, tgapi_config_dev)
        write(tables / "msg.py", tgapi_data_msg.replace("from data", f"from {tables_name}"))
    write("main.py", main_tgapi if with_tgapi else main)
    if force or not (root / ".gitignore").exists():
        gitignore = gitignore_base
        ignored_paths = (
            ([config.db_dev_path] if not config.db_dev_path.startswith("ENV:") else [])
            + [
                config.log_info_path,
                config.log_requests_path,
                config.log_errors_path,
                config.log_frontend_path,
                config.jwt_key_file_path,
                config.images_folder if config.images_folder[-1] == "/" else config.images_folder + "/",
            ]
            + (
                [
                    cast(str, config.log_bot_path),
                    cast(str, config.config_path),
                    cast(str, config.config_dev_path),
                ]
                if with_tgapi
                else []
            )
        )
        gitignore += "\n" + "\n".join(entry for path in ignored_paths if (entry := _gitignore_entry(root, path)) is not None)
        write(".gitignore", gitignore)
    if config.use_alembic:
        folder = root / config.migrations_folder
        init_migrations(["--force"] if force else [], folder=str(folder))


def write_file(path: str, text: str, *, force: bool = False):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w" if force else "x", encoding="utf8") as f:
            f.write(text)
    except FileExistsError:
        print(f"Skipping existing file: {path}")


def run(args: list[str]):
    options = parse_init_project_args(args)
    init_project(force=options.force, directory=options.directory)


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

blueprints_docs_py = """from bafser import get_app_config, render_docs_page
from flask import Blueprint, abort

bp = Blueprint("docs", __name__)


@bp.route("/api")
def docs():
    if not get_app_config().DEV_MODE:
        abort(404)
    return render_docs_page()
"""

main = """import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from bafser import AppConfig, create_app


app, run = create_app(__name__, AppConfig(
    MESSAGE_TO_FRONTEND="",
    DEV_MODE="dev" in sys.argv,
    DELAY_MODE="delay" in sys.argv,
))

run(__name__ == "__main__")
"""
main_tgapi = """import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

import bafser_tgapi as tgapi
from bafser import AppConfig, create_app

from bot.bot import Bot

app, run = create_app(__name__, AppConfig(DEV_MODE="dev" in sys.argv))
tgapi.setup(botCls=Bot, app=app)

DEVSERVER = "devServer" in sys.argv
if "--setup" in sys.argv:
    run(False)
else:
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
