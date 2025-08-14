from sqlalchemy.orm import Session, Mapped, mapped_column

from .. import SqlAlchemyBase, SingletonMixin


class DBState(SqlAlchemyBase, SingletonMixin):
    __tablename__ = "db_state"

    initialized: Mapped[bool] = mapped_column(server_default="0", init=False)

    @staticmethod
    def is_initialized(db_sess: Session):
        return DBState.get(db_sess).initialized

    @staticmethod
    def mark_as_initialized(db_sess: Session):
        DBState.get(db_sess).initialized = True
        db_sess.commit()
