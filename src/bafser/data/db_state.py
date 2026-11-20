from sqlalchemy.orm import Mapped, Session, mapped_column

from .. import SingletonMixin, SqlAlchemyBase


class DBState(SqlAlchemyBase, SingletonMixin):
    __tablename__ = "db_state"

    initialized: Mapped[bool] = mapped_column(server_default="0", init=False)

    @staticmethod
    def is_initialized(db_sess: Session, *, commit: bool = True) -> bool:
        return bool(DBState.get(db_sess=db_sess, commit=commit).initialized)

    @staticmethod
    def mark_as_initialized(db_sess: Session, *, commit: bool = True):
        DBState.get(db_sess=db_sess, commit=False).initialized = True
        if commit:
            db_sess.commit()
