import os

from alembic.config import Config
from alembic import command

from .utils import get_db_path
import bafser_config


def create_alembic_config(dev: bool):
    alembic_cfg = Config()
    alembic_cfg.set_main_option("script_location", bafser_config.migrations_folder)
    alembic_cfg.set_main_option("file_template", "%%(year)d_%%(month).2d_%%(day).2d_%%(rev)s_%%(slug)s")

    if dev:
        db_path = bafser_config.db_dev_path
        issqlite = True
    else:
        db_path = get_db_path(bafser_config.db_path)
        issqlite = not bafser_config.db_mysql
    alembic_cfg.set_main_option("issqlite", "1" if issqlite else "0")

    if issqlite:
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}?check_same_thread=False")
        if not os.path.exists(db_path):
            dirname = os.path.dirname(db_path)
            if dirname != "":
                os.makedirs(dirname, exist_ok=True)
            with open(db_path, "w"):
                pass
    else:
        alembic_cfg.set_main_option("sqlalchemy.url", f"mysql+pymysql://{db_path}?charset=UTF8mb4")
    return alembic_cfg


def alembic_upgrade(dev: bool):
    alembic_cfg = create_alembic_config(dev)
    command.upgrade(alembic_cfg, "head")


def run():
    from logging.config import fileConfig
    from sqlalchemy import engine_from_config
    from sqlalchemy import pool

    from alembic import context
    config = context.config
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)

    from .db_session import SqlAlchemyBase
    from .utils.import_all_tables import import_all_tables
    import_all_tables()
    target_metadata = SqlAlchemyBase.metadata

    issqlite = config.get_main_option("issqlite") == "1"

    def run_migrations_offline() -> None:
        """Run migrations in 'offline' mode.

        This configures the context with just a URL
        and not an Engine, though an Engine is acceptable
        here as well.  By skipping the Engine creation
        we don't even need a DBAPI to be available.

        Calls to context.execute() here emit the given string to the
        script output.

        """
        url = config.get_main_option("sqlalchemy.url")
        context.configure(
            url=url,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            render_as_batch=issqlite,
        )

        with context.begin_transaction():
            context.run_migrations()

    def run_migrations_online() -> None:
        """Run migrations in 'online' mode.

        In this scenario we need to create an Engine
        and associate a connection with the context.

        """
        connectable = engine_from_config(
            config.get_section(config.config_ini_section, {}),
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=issqlite,
            )

            with context.begin_transaction():
                context.run_migrations()

    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()
