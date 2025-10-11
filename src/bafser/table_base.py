from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, Session, mapped_column
from sqlalchemy_serializer import SerializerMixin
from typing_extensions import Annotated

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
    __fields_hidden_in_log__ = [""]
    metadata = MetaData(naming_convention=convention)

    def __repr__(self):
        return f"<{self.__class__.__name__}>"

    def get_dict(self) -> object:
        return self.to_dict()

    def get_session(self):
        return Session.object_session(self)

    @property
    def db_sess(self):
        db_sess = self.get_session()
        assert db_sess, "object is not bound to session"
        return db_sess


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
    def query2(cls, *, for_update: bool = False):
        """Calls self.query with db session from global context"""
        from . import get_db_session
        return cls.query(get_db_session(), for_update=for_update)

    @classmethod
    def get(cls, db_sess: Session, id: int, *, for_update: bool = False):
        return cls.query(db_sess, for_update=for_update).filter(cls.id == id).first()

    @classmethod
    def get2(cls, id: int, *, for_update: bool = False):
        """Calls self.get with db session from global context"""
        from . import get_db_session
        return cls.get(get_db_session(), id, for_update=for_update)

    @classmethod
    def all(cls, db_sess: Session, *, for_update: bool = False):
        return cls.query(db_sess, for_update=for_update).all()

    @classmethod
    def all2(cls, *, for_update: bool = False):
        """Calls self.all with db session from global context"""
        from . import get_db_session
        return cls.all(get_db_session(), for_update=for_update)

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
    def query2(cls, includeDeleted: bool = False, *, for_update: bool = False):  # pyright: ignore[reportIncompatibleMethodOverride]
        """Calls self.query with db session from global context"""
        from . import get_db_session
        return cls.query(get_db_session(), includeDeleted, for_update=for_update)

    @classmethod
    def get(cls, db_sess: Session, id: int, includeDeleted: bool = False, *, for_update: bool = False):
        return cls.query(db_sess, includeDeleted, for_update=for_update).filter(cls.id == id).first()

    @classmethod
    def get2(cls, id: int, includeDeleted: bool = False, *, for_update: bool = False):
        """Calls self.get with db session from global context"""
        from . import get_db_session
        return cls.get(get_db_session(), id, includeDeleted, for_update=for_update)

    @classmethod
    def all(cls, db_sess: Session, includeDeleted: bool = False, *, for_update: bool = False):  # pyright: ignore[reportIncompatibleMethodOverride]
        return cls.query(db_sess, includeDeleted, for_update=for_update).all()

    @classmethod
    def all2(cls, includeDeleted: bool = False, *, for_update: bool = False):  # pyright: ignore[reportIncompatibleMethodOverride]
        """Calls self.all with db session from global context"""
        from . import get_db_session
        return cls.all(get_db_session(), includeDeleted, for_update=for_update)

    def delete(self, actor: "UserBase", commit: bool = True, now: datetime | None = None, db_sess: Session | None = None):
        from . import Log, get_datetime_now
        now = get_datetime_now() if now is None else now
        db_sess = db_sess if db_sess else actor.db_sess
        if not self._on_delete(db_sess, actor, now, commit):
            return False
        self.deleted = True
        if isinstance(self, TableBase):
            Log.deleted(self, actor, now=now, commit=commit, db_sess=db_sess)
        return True

    def delete2(self, commit: bool = True, now: datetime | None = None):
        """Calls self.delete with UserBase.current as actor"""
        return self.delete(UserBase.current, commit, now, None)

    def _on_delete(self, db_sess: Session, actor: "UserBase", now: datetime, commit: bool) -> bool:
        """override to add logic on delete, return True if obj can be deleted"""
        return True

    def restore(self, actor: "UserBase", commit: bool = True, now: datetime | None = None, db_sess: Session | None = None) -> bool:
        from . import Log, get_datetime_now
        now = get_datetime_now() if now is None else now
        db_sess = db_sess if db_sess else actor.db_sess
        if not self._on_restore(db_sess, actor, now, commit):
            return False
        self.deleted = False
        if isinstance(self, TableBase):
            Log.restored(self, actor, now=now, commit=commit, db_sess=db_sess)
        return True

    def restore2(self, commit: bool = True, now: datetime | None = None):
        """Calls self.restore with UserBase.current as actor"""
        return self.restore(UserBase.current, commit, now, None)

    def _on_restore(self, db_sess: Session, actor: "UserBase", now: datetime, commit: bool) -> bool:
        """override to add logic on restore, return True if obj can be restored"""
        return True

    def __repr__(self):
        r = f"<{self.__class__.__name__}> [{self.id}]"
        if self.deleted:
            r += " deleted"
        return r


class SingletonMixin:
    _ID = 1
    id: Mapped[intpk] = mapped_column(init=False)

    @classmethod
    def get(cls, db_sess: Session):
        obj = db_sess.get(cls, cls._ID)
        if obj:
            return obj
        obj = cls()
        obj.id = cls._ID
        obj.init()
        db_sess.add(obj)
        db_sess.commit()
        return obj

    @classmethod
    def get2(cls):
        from . import get_db_session
        return cls.get(get_db_session())

    def init(self):
        pass
