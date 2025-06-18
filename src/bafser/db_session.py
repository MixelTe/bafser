from typing import Type

from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import FunctionFilter
from sqlalchemy.sql.functions import Function
import sqlalchemy as sa
import sqlalchemy.ext.declarative as dec
import sqlalchemy.orm as orm

from .table_base import TableBase
from .utils import import_all_tables
import bafser_config


convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}
SqlAlchemyBase: Type[TableBase] = dec.declarative_base(cls=TableBase)
SqlAlchemyBase.metadata = sa.MetaData(naming_convention=convention)

__factory = None


def global_init(dev: bool):
    global __factory

    if __factory:
        return

    if dev:
        conn_str = f"sqlite:///{bafser_config.db_dev_path}?check_same_thread=False"
    else:
        if bafser_config.db_mysql:
            conn_str = f"mysql+pymysql://{bafser_config.db_path}?charset=UTF8mb4"
        else:
            conn_str = f"sqlite:///{bafser_config.db_path}?check_same_thread=False"
    print(f"Подключение к базе данных по адресу {conn_str}")

    engine = sa.create_engine(conn_str, echo=bafser_config.sql_echo, pool_pre_ping=True)
    __factory = orm.sessionmaker(bind=engine)

    import_all_tables()

    SqlAlchemyBase.metadata.create_all(engine)


def create_session() -> orm.Session:
    return __factory()


# @sa.event.listens_for(sa.engine.Engine, 'connect')
# def sqlite_engine_connect(dbapi_conn, connection_record):
#     dbapi_conn.create_function('lower', 1, str.lower)


@compiles(FunctionFilter, 'mysql')
def compile_functionfilter_mysql(element, compiler, **kwgs):
    # Support unary functions only
    arg0, = element.func.clauses

    new_func = Function(
        element.func.name,
        sa.case([(element.criterion, arg0)]),
        packagenames=element.func.packagenames,
        type_=element.func.type,
        bind=element.func._bind)

    return new_func._compiler_dispatch(compiler, **kwgs)
