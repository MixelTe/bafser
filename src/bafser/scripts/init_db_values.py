import sys
import os


def init_db_values(dev=False, cmd=False):
    print(f"init_db_values {dev=}")
    if cmd:
        add_root_to_path()

    from bafser import db_session, Role, UserBase, create_folder_for_file

    if dev:
        import bfs_config
        create_folder_for_file(bfs_config.db_dev_path)

    db_session.global_init(dev)
    db_sess = db_session.create_session()

    Role.update_roles_permissions(db_sess)
    UserBase._create_admin(db_sess)

    db_sess.close()


def add_root_to_path():
    current = os.path.dirname(os.path.realpath(__file__))
    root = os.path.dirname(os.path.dirname(current))
    sys.path.append(root)


if __name__ == "__main__":
    init_db_values("dev" in sys.argv, True)
