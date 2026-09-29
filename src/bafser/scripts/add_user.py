import sys


def add_user(login: str, password: str, name: str, roleId: int, dev: bool):
    print(f"add_user {login=} {name=} {roleId=} {dev=}")
    from bafser import Role, db_session
    from bafser.data.user import get_user_table

    db_session.global_init(dev)
    with db_session.create_session() as db_sess:
        User = get_user_table()
        user_admin = User.get_admin(db_sess)
        assert user_admin
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


def run(args: list[str]):
    if not (len(args) == 3 or (len(args) == 4 and args[-1] == "dev")):
        print("add_user: login name roleId [dev] < password.txt")
    else:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise ValueError("Password must be provided on stdin")
        add_user(args[0], password, args[1], int(args[2]), args[-1] == "dev")
