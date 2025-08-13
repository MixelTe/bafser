def change_user_password(login: str, password: str, dev: bool):
    print(f"change_user_password {login=} {password=} {dev=}")
    from bafser import db_session
    from bafser.data.user import get_user_table

    db_session.global_init(dev)
    with db_session.create_session() as db_sess:
        User = get_user_table()
        user = User.get_by_login(db_sess, login, includeDeleted=True)
        if user is None:
            print("User does not exist")
            return
        user.set_password(password)
        db_sess.commit()
        print("Password changed")


def run(args: list[str]):
    if not (len(args) == 2 or (len(args) == 3 and args[-1] == "dev")):
        print("change_user_password: login new_password [dev]")
    else:
        change_user_password(args[0], args[1], args[-1] == "dev")
