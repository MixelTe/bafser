from collections.abc import Callable

from flask import g
from sqlalchemy.orm import Session


def get_db_session() -> Session:
    return _getter(_get_db_session)


def _get_db_session() -> Session:
    from .. import db_session

    if "db_session" not in g:
        g.db_session = db_session.create_session()
    return g.db_session


DefaultGetter = Callable[[], Session]
_getter: Callable[[DefaultGetter], Session] = lambda get: get()


def override_get_db_session(getter: Callable[[DefaultGetter], Session]):
    global _getter
    _getter = getter
