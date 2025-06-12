import sys
import os


def add_user(login, password, name, roleId, dev):
    roleId = int(roleId)
    print(f"add_user {login=} {password=} {name=} {roleId=} {dev=}")
    add_root_to_path()
    from bafser import db_session, Role
    from bafser.data.user import get_user_table

    db_session.global_init("dev" in sys.argv)
    db_sess = db_session.create_session()
    User = get_user_table()
    user_admin = User.get_admin(db_sess)
    existing = User.get_by_login(db_sess, login, includeDeleted=True)
    if existing:
        print(f"User with login [{login}] already exist")
        return
    role = db_sess.get(Role, roleId)
    if not role:
        print(f"Role with id [{roleId}] does not exist")
        return

    User.new(user_admin, login, password, name, [roleId])

    print("User added")


def add_root_to_path():
    current = os.path.dirname(os.path.realpath(__file__))
    root = os.path.dirname(os.path.dirname(current))
    sys.path.append(root)


if not (len(sys.argv) == 5 or (len(sys.argv) == 6 and sys.argv[-1] == "dev")):
    print("add_user: login password name roleId [dev]")
else:
    add_user(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[-1] == "dev")
