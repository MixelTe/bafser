from datetime import datetime
from typing import TYPE_CHECKING
from typing_extensions import Annotated

from sqlalchemy import MetaData
from sqlalchemy.orm import Session, DeclarativeBase, MappedAsDataclass, Mapped, mapped_column
from sqlalchemy_serializer import SerializerMixin

if TYPE_CHECKING:
    from . import UserBase

convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}


class TableBase(SerializerMixin, MappedAsDataclass, DeclarativeBase):
    __abstract__ = True
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}
    metadata = MetaData(naming_convention=convention)

    def __repr__(self):
        return f"<{self.__class__.__name__}>"

    def get_dict(self) -> object:
        return {}


intpk = Annotated[int, mapped_column(primary_key=True, unique=True, autoincrement=True)]


class IdMixin:
    id: Mapped[intpk] = mapped_column(init=False)

    @classmethod
    def query(cls, db_sess: Session, *, for_update: bool = False):
        q = db_sess.query(cls)
        if for_update:
            q = q.with_for_update()
        return q

    @classmethod
    def get(cls, db_sess: Session, id: int, *, for_update: bool = False):
        return cls.query(db_sess, for_update=for_update).filter(cls.id == id).first()

    @classmethod
    def all(cls, db_sess: Session, *, for_update: bool = False):
        return cls.query(db_sess, for_update=for_update).all()

    def __repr__(self):
        return f"<{self.__class__.__name__}> [{self.id}]"


class ObjMixin(IdMixin):
    deleted: Mapped[bool] = mapped_column(server_default="0", init=False)

    @classmethod
    def query(cls, db_sess: Session, includeDeleted: bool = False, *, for_update: bool = False):  # pyright: ignore[reportIncompatibleMethodOverride]
        items = db_sess.query(cls)
        if for_update:
            items = items.with_for_update()
        if not includeDeleted:
            items = items.filter(cls.deleted == False)
        return items

    @classmethod
    def get(cls, db_sess: Session, id: int, includeDeleted: bool = False, *, for_update: bool = False):
        return cls.query(db_sess, includeDeleted, for_update=for_update).filter(cls.id == id).first()

    @classmethod
    def all(cls, db_sess: Session, includeDeleted: bool = False, *, for_update: bool = False):  # pyright: ignore[reportIncompatibleMethodOverride]
        return cls.query(db_sess, includeDeleted, for_update=for_update).all()

    def delete(self, actor: "UserBase", commit: bool = True, now: datetime | None = None, db_sess: Session | None = None):
        from . import Log, get_datetime_now
        now = get_datetime_now() if now is None else now
        db_sess = db_sess if db_sess else Session.object_session(actor)
        assert db_sess
        if not self._on_delete(db_sess, actor, now, commit):
            return False
        self.deleted = True
        if isinstance(self, TableBase):
            Log.deleted(self, actor, now=now, commit=commit, db_sess=db_sess)
        return True

    def _on_delete(self, db_sess: Session, actor: "UserBase", now: datetime, commit: bool) -> bool:
        return True

    def restore(self, actor: "UserBase", commit: bool = True, now: datetime | None = None, db_sess: Session | None = None) -> bool:
        from . import Log, get_datetime_now
        now = get_datetime_now() if now is None else now
        db_sess = db_sess if db_sess else Session.object_session(actor)
        assert db_sess
        if not self._on_restore(db_sess, actor, now, commit):
            return False
        self.deleted = False
        if isinstance(self, TableBase):
            Log.restored(self, actor, now=now, commit=commit, db_sess=db_sess)
        return True

    def _on_restore(self, db_sess: Session, actor: "UserBase", now: datetime, commit: bool) -> bool:
        return True


class SingletonMixin:
    id: Mapped[intpk] = mapped_column(init=False)

    @classmethod
    def get(cls, db_sess: Session):
        obj = db_sess.get(cls, 1)
        if obj:
            return obj
        obj = cls()
        obj.id = 1
        obj.init()
        db_sess.add(obj)
        db_sess.commit()
        return obj

    def init(self):
        pass
