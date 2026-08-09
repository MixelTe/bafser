import importlib
import sys


def cli():
    scripts = [
        ("init_project", ""),
        ("add_user_role", "userId roleId [dev]"),
        ("add_user", "login password name roleId [dev]"),
        ("change_user_password", "login new_password [dev]"),
        ("remove_user_role", "userId roleId [dev]"),
        ("alembic", "<init | revision | upgrade>"),
    ]

    try:
        import bafser_tgapi  # type: ignore

        scripts.append(("configure_webhook", "<set | delete> [dev]"))
        scripts.append(("stickers", ""))
    except Exception:  # noqa: S110
        pass

    if len(sys.argv) < 2 or sys.argv[1] not in (v[0] for v in scripts):
        ml = max(len(v[0]) for v in scripts)
        ml2 = max(len(v[1]) for v in scripts)
        l = ml + ml2 + 5
        t = " Scripts "
        l2 = l - len(t)
        print("-" * (l2 // 2) + t + "-" * (l2 // 2 + l2 % 2))
        print("\n".join(f"{' ' * (ml - len(v[0]))} {v[0]} : {v[1]}" for v in scripts))
        print("-" * l)
        return

    importlib.import_module(".scripts." + sys.argv[1], "bafser").run(sys.argv[2:])
