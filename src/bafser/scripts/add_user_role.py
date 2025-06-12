def add_user_role(userId, roleId, dev):
    userId, roleId = int(userId), int(roleId)
    print(f"add_user_role {userId=} {roleId=} {dev=}")
    from bafser import db_session, Role
    from bafser.data.user import get_user_table

    db_session.global_init(dev)
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

    ok = user.add_role(user_admin, roleId)

    if not ok:
        print(f"User [{user.login}] already has [{role.name}] role")
        return

    print(f"Role [{role.name}] added to User [{user.login}]")


def run(args):
    if not (len(args) == 2 or (len(args) == 3 and args[-1] == "dev")):
        print("add_user_role: userId roleId [dev]")
    else:
        add_user_role(args[0], args[1], args[-1] == "dev")
