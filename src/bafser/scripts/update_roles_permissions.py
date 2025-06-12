def update_roles_permissions(dev: bool):
    print(f"update_roles_permissions {dev=}")
    from bafser import db_session, Role

    db_session.global_init(dev)
    db_sess = db_session.create_session()
    Role.update_roles_permissions(db_sess)

    print("/update_roles_permissions")


def run(args):
    update_roles_permissions("dev" in args)
