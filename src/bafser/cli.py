import importlib
import sys
from pathlib import Path

from dotenv import load_dotenv


def cli():
    project_dir = Path.cwd().resolve()
    load_dotenv(project_dir / ".env", override=False)
    project_import_path = str(project_dir)
    if project_import_path not in sys.path:
        sys.path.insert(0, project_import_path)

    scripts = [
        ("init_project", "[--force] [--directory PATH]"),
        ("add_user_role", "userId roleId [dev]"),
        ("add_user", "login name roleId [dev] < password.txt"),
        ("change_user_password", "login [dev] < password.txt"),
        ("remove_user_role", "userId roleId [dev]"),
        ("alembic", "<init | revision | upgrade>"),
    ]

    try:
        importlib.import_module("bafser_tgapi")

        scripts.append(("configure_webhook", "<set | delete> [dev]"))
        scripts.append(("stickers", ""))
    except Exception:
        pass

    if len(sys.argv) < 2 or sys.argv[1] not in (v[0] for v in scripts):
        ml = max(len(v[0]) for v in scripts)
        ml2 = max(len(v[1]) for v in scripts)
        line_width = ml + ml2 + 5
        t = " Scripts "
        l2 = line_width - len(t)
        print("-" * (l2 // 2) + t + "-" * (l2 // 2 + l2 % 2))
        print("\n".join(f"{' ' * (ml - len(v[0]))} {v[0]} : {v[1]}" for v in scripts))
        print("-" * line_width)
        return

    importlib.import_module(".scripts." + sys.argv[1], "bafser").run(sys.argv[2:])
