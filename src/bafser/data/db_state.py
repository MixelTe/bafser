from sqlalchemy import Boolean, Column, DefaultClause
from sqlalchemy.orm import Session

from .. import SqlAlchemyBase, SingletonMixin


class DBState(SqlAlchemyBase, SingletonMixin):
    __tablename__ = "db_state"

    initialized = Column(Boolean, DefaultClause("0"), nullable=False)

    @staticmethod
    def is_initialized(db_sess: Session):
        return DBState.get(db_sess).initialized

    @staticmethod
    def mark_as_initialized(db_sess: Session):
        DBState.get(db_sess).initialized = True
        db_sess.commit()
