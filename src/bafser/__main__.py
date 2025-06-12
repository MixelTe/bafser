import importlib
import sys


def cli():
    scripts = [
        ("add_user_role", "userId roleId [dev]"),
        ("add_user", "login password name roleId [dev]"),
        ("change_user_password", "login new_password [dev]"),
        ("init_db_values", "[dev]"),
        ("remove_user_role", "userId roleId [dev]"),
        ("update_roles_permissions", "[dev]"),
    ]

    if len(sys.argv) < 2 or sys.argv[1] not in map(lambda v: v[0], scripts):
        ml = max(map(lambda v: len(v[0]), scripts))
        ml2 = max(map(lambda v: len(v[1]), scripts))
        l = ml + ml2 + 5
        t = " Scripts "
        l2 = (l - len(t))
        print("-" * (l2 // 2) + t + "-" * (l2 // 2 + l2 % 2))
        print("\n".join(map(lambda v: f"{' ' * (ml - len(v[0]))} {v[0]} : {v[1]}", scripts)))
        print("-" * l)
        return

    importlib.import_module("scripts." + sys.argv[1], "bafser").run(sys.argv[2:])


if __name__ == "__main__":
    cli()
