def init_db_values(dev=False):
    print(f"init_db_values {dev=}")

    from bafser import db_session, Role, UserBase, create_folder_for_file

    if dev:
        import bafser_config
        create_folder_for_file(bafser_config.db_dev_path)

    db_session.global_init(dev)
    db_sess = db_session.create_session()

    Role.update_roles_permissions(db_sess)
    UserBase._create_admin(db_sess)

    db_sess.close()


def run(args):
    init_db_values("dev" in args)
