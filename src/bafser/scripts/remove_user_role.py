def remove_user_role(userId: int, roleId: int, dev: bool):
    print(f"remove_user_role {userId=} {roleId=} {dev=}")
    from bafser import db_session, Role
    from bafser.data.user import get_user_table

    db_session.global_init(dev)
    with db_session.create_session() as db_sess:
        User = get_user_table()
        user_admin = User.get_admin(db_sess)
        assert user_admin
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


def run(args: list[str]):
    if not (len(args) == 2 or (len(args) == 3 and args[-1] == "dev")):
        print("remove_user_role: userId roleId [dev]")
    else:
        remove_user_role(int(args[0]), int(args[1]), args[-1] == "dev")
