from typing import Callable

from flask import g
from sqlalchemy.orm import Session


def get_db_session() -> Session:
    return _getter(_get_db_session)


def _get_db_session() -> Session:
    from .. import db_session
    if "db_session" not in g:
        g.db_session = db_session.create_session()
    return g.db_session


type defaultGetter = Callable[[], Session]
_getter: Callable[[defaultGetter], Session] = lambda get: get()


def override_get_db_session(getter: Callable[[defaultGetter], Session]):
    global _getter
    _getter = getter
