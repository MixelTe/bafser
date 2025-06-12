import sys
import os


def update_roles_permissions():
    dev = "dev" in sys.argv
    print(f"update_roles_permissions {dev=}")
    add_root_to_path()
    from bafser import db_session, Role

    db_session.global_init(dev)
    db_sess = db_session.create_session()
    Role.update_roles_permissions(db_sess)

    print("/update_roles_permissions")


def add_root_to_path():
    current = os.path.dirname(os.path.realpath(__file__))
    root = os.path.dirname(os.path.dirname(current))
    sys.path.append(root)


update_roles_permissions()
