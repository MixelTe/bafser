import sys
import os


def remove_user_role(userId, roleId, dev):
    userId, roleId = int(userId), int(roleId)
    print(f"remove_user_role {userId=} {roleId=} {dev=}")
    add_root_to_path()
    from bafser import db_session, Role
    from bafser.data.user import get_user_table

    db_session.global_init("dev" in sys.argv)
    db_sess = db_session.create_session()
    User = get_user_table()
    user_admin = User.get_admin(db_sess)
    user = db_sess.get(User, userId)
    if not user:
        print(f"User with id [{userId}] does not exist")
        return
    role = db_sess.get(Role, roleId)
    if not role:
        print(f"Role with id [{roleId}] does not exist")
        return

    ok = user.remove_role(user_admin, roleId)

    if not ok:
        print(f"User [{user.login}] does not has [{role.name}] role")
        return

    print(f"Role [{role.name}] removed from User [{user.login}]")


def add_root_to_path():
    current = os.path.dirname(os.path.realpath(__file__))
    root = os.path.dirname(os.path.dirname(current))
    sys.path.append(root)


if not (len(sys.argv) == 3 or (len(sys.argv) == 4 and sys.argv[-1] == "dev")):
    print("remove_user_role: userId roleId [dev]")
else:
    remove_user_role(sys.argv[1], sys.argv[2], sys.argv[-1] == "dev")
