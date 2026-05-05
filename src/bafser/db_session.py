from typing import Any

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import event
from sqlalchemy.engine import Engine

import bafser_config

from .table_base import TableBase as SqlAlchemyBase
from .utils import create_folder_for_file, get_db_path, import_all_tables

__factory = None


def global_init(dev: bool):
    global __factory

    if __factory:
        return

    if dev:
        db_path = get_db_path(bafser_config.db_dev_path)
        setup_sqlite(db_path)
        conn_str = f"sqlite:///{db_path}?check_same_thread=False"
    else:
        db_path = get_db_path(bafser_config.db_path)
        if bafser_config.db_mysql:
            conn_str = f"mysql+pymysql://{db_path}?charset=UTF8mb4"
        else:
            setup_sqlite(db_path)
            conn_str = f"sqlite:///{db_path}?check_same_thread=False"
    print(f"Connecting to the database at {conn_str}")

    engine = sa.create_engine(
        conn_str,
        echo=bafser_config.sql_echo,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=3600,
    )
    __factory = orm.sessionmaker(bind=engine)

    import_all_tables()

    SqlAlchemyBase.metadata.create_all(engine)


def create_session() -> orm.Session:
    return __factory()  # type: ignore


def setup_sqlite(db_path: str):
    create_folder_for_file(db_path)

    @event.listens_for(Engine, "connect")
    def _(dbapi_connection: Any, connection_record: Any):
        dbapi_connection.create_function("lower", 1, str.lower)
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
