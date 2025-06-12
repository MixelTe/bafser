def change_user_password(login, password, dev):
    print(f"change_user_password {login=} {password=} {dev=}")
    from bafser import db_session
    from bafser.data.user import get_user_table

    db_session.global_init(dev)
    db_sess = db_session.create_session()
    User = get_user_table()
    user = User.get_by_login(db_sess, login, includeDeleted=True)
    if user is None:
        print("User does not exist")
        return
    user.set_password(password)
    db_sess.commit()
    print("Password changed")


def run(args):
    if not (len(args) == 2 or (len(args) == 3 and args[-1] == "dev")):
        print("change_user_password: login new_password [dev]")
    else:
        change_user_password(args[0], args[1], args[-1] == "dev")
