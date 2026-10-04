import sys


def change_user_password(login: str, password: str, dev: bool):
    print(f"change_user_password {login=} {dev=}")
    from bafser import db_session
    from bafser.data.user import get_user_table

    db_session.global_init(dev)
    with db_session.create_session() as db_sess:
        User = get_user_table()
        user = User.get_by_login(login, includeDeleted=True, db_sess=db_sess)
        if user is None:
            print("User does not exist")
            return
        user.set_password(password)
        db_sess.commit()
        print("Password changed")


def run(args: list[str]):
    if not (len(args) == 1 or (len(args) == 2 and args[-1] == "dev")):
        print("change_user_password: login [dev] < password.txt")
    else:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise ValueError("Password must be provided on stdin")
        change_user_password(args[0], password, args[-1] == "dev")
