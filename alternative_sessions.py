import contextvars
from contextlib import contextmanager
from typing import Any

import sqlalchemy.orm as orm
from sqlalchemy.orm import Mapped, Session

__factory: Any = None
db_session_var = contextvars.ContextVar[Session]("db_session")


def example():
    with db_session():
        a = Mixin.get(1)
        print(a)


@contextmanager
def db_session():
    existing_session = db_session_var.get(None)
    if existing_session:
        yield existing_session
        return
    session: orm.Session = __factory()  # type: ignore
    token = db_session_var.set(session)
    try:
        yield session
    finally:
        db_session_var.reset(token)
        session.close()


class Mixin:
    id: Mapped[int]

    @classmethod
    def query(cls, *, for_update: bool = False):
        db_sess = db_session_var.get()
        q = db_sess.query(cls)
        if for_update:
            q = q.with_for_update()
        return q

    @classmethod
    def get(cls, id: int, *, for_update: bool = False):
        return cls.query(for_update=for_update).filter(cls.id == id).first()

    @classmethod
    def all(cls, *, for_update: bool = False):
        return cls.query(for_update=for_update).all()

    def __repr__(self):
        return f"<{self.__class__.__name__}> [{self.id}]"
