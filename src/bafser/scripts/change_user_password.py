import sys
import os


def change_user_password(login, password, dev):
    print(f"change_user_password {login=} {password=} {dev=}")
    add_root_to_path()
    from bafser import db_session
    from bafser.data.user import get_user_table

    db_session.global_init("dev" in sys.argv)
    db_sess = db_session.create_session()
    User = get_user_table()
    user = User.get_by_login(db_sess, login, includeDeleted=True)
    if user is None:
        print("User does not exist")
        return
    user.set_password(password)
    db_sess.commit()
    print("Password changed")


def add_root_to_path():
    current = os.path.dirname(os.path.realpath(__file__))
    root = os.path.dirname(os.path.dirname(current))
    sys.path.append(root)


if not (len(sys.argv) == 3 or (len(sys.argv) == 4 and sys.argv[-1] == "dev")):
    print("change_user_password: login new_password [dev]")
else:
    change_user_password(sys.argv[1], sys.argv[2], sys.argv[-1] == "dev")
