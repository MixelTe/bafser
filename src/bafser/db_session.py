from threading import RLock
from typing import Any

import sqlalchemy as sa
from sqlalchemy import event, orm
from sqlalchemy.engine import URL, Engine

import bafser_config

from .table_base import TableBase as SqlAlchemyBase
from .utils import create_folder_for_file, get_db_path, get_mysql_url, import_all_tables

__factory: orm.sessionmaker[orm.Session] | None = None
__engine: Engine | None = None
__settings: tuple[Any, ...] | None = None
_init_lock = RLock()


def _engine_options(dev: bool, sqlite: bool) -> dict[str, Any]:
    hidden = getattr(bafser_config, "db_hide_parameters", None)
    options: dict[str, Any] = {
        "echo": bafser_config.sql_echo,
        "hide_parameters": not dev if hidden is None else hidden,
        "pool_pre_ping": True,
        "pool_recycle": getattr(bafser_config, "db_pool_recycle", 3600),
    }
    if not sqlite or get_db_path(bafser_config.db_dev_path if dev else bafser_config.db_path) != ":memory:":
        options.update(
            pool_size=getattr(bafser_config, "db_pool_size", 5),
            max_overflow=getattr(bafser_config, "db_max_overflow", 10),
            pool_timeout=getattr(bafser_config, "db_pool_timeout", 30),
        )
    if not sqlite:
        options["connect_args"] = {
            "connect_timeout": getattr(bafser_config, "db_connect_timeout", 10),
            "read_timeout": getattr(bafser_config, "db_read_timeout", 30),
            "write_timeout": getattr(bafser_config, "db_write_timeout", 30),
        }
    return options


def global_init(dev: bool, *, create_tables: bool = False) -> None:
    """Configure one process-owned engine; schema creation is explicit setup.

    Sessions already checked out must be closed before dispose/reconfiguration.
    Repeating the same initialization is safe; changing it requires an explicit
    dispose so a second application cannot silently use the first one's DB.
    """
    global __factory, __engine, __settings

    sqlite = dev or not bafser_config.db_mysql
    db_path: str | None = None
    if sqlite:
        db_path = get_db_path(bafser_config.db_dev_path if dev else bafser_config.db_path)
        url = URL.create("sqlite", database=db_path, query={"check_same_thread": "False"})
    else:
        url = get_mysql_url(bafser_config.db_path)
    options = _engine_options(dev, sqlite)
    settings = (url, dev, tuple((key, repr(value)) for key, value in options.items()))

    with _init_lock:
        if __factory is not None:
            if settings != __settings:
                raise RuntimeError("Database is already initialized with different settings; dispose it before reconfiguration")
        if create_tables and db_path is not None and db_path != ":memory:":
            create_folder_for_file(db_path)
        if __factory is not None:
            if create_tables:
                import_all_tables()
                SqlAlchemyBase.metadata.create_all(get_engine())
            return

        import_all_tables()
        engine = sa.create_engine(url, **options)
        try:
            if sqlite:
                setup_sqlite(engine)
            if create_tables:
                SqlAlchemyBase.metadata.create_all(engine)
        except BaseException:
            engine.dispose()
            raise
        __engine = engine
        __factory = orm.sessionmaker(bind=engine)
        __settings = settings


def get_engine() -> Engine:
    """Return the configured engine without opening a connection."""
    with _init_lock:
        if __engine is None:
            raise RuntimeError("Database is not initialized; call global_init first")
        return __engine


def dispose_engine() -> None:
    """Release the pool and reset process state after sessions have been closed."""
    global __factory, __engine, __settings
    with _init_lock:
        if __engine is not None:
            __engine.dispose()
        __factory = None
        __engine = None
        __settings = None


def create_session() -> orm.Session:
    with _init_lock:
        if __factory is None:
            raise RuntimeError("Database is not initialized; call global_init first")
        return __factory()


def setup_sqlite(engine: Engine) -> None:
    """Register SQLite-only callbacks on this engine, never the Engine class."""

    @event.listens_for(engine, "connect")
    def _(dbapi_connection: Any, connection_record: Any):
        dbapi_connection.create_function("lower", 1, lambda value: value.lower() if value is not None else None)  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
