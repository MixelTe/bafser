def add_user(login: str, password: str, name: str, roleId: int, dev: bool):
    print(f"add_user {login=} {password=} {name=} {roleId=} {dev=}")
    from bafser import db_session, Role
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
    if not (len(args) == 4 or (len(args) == 5 and args[-1] == "dev")):
        print("add_user: login password name roleId [dev]")
    else:
        add_user(args[0], args[1], args[2], int(args[3]), args[-1] == "dev")
