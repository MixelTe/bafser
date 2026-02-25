from datetime import datetime
from typing import TYPE_CHECKING, Type, TypeVar

from sqlalchemy import MetaData, String
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
    "pk": "pk_%(table_name)s",
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
    """Mixin providing an integer primary key and common query helpers."""

    id: Mapped[intpk] = mapped_column(init=False)

    @classmethod
    def query(cls, db_sess: Session, *, for_update: bool = False):
        q = db_sess.query(cls)
        if for_update:
            q = q.with_for_update()
        return q

    @classmethod
    def query2(cls, *, for_update: bool = False, db_sess: Session | None = None):
        """Calls cls.query with db session from global context"""
        from . import get_db_session

        return cls.query(db_sess or get_db_session(), for_update=for_update)

    @classmethod
    def get(cls, db_sess: Session, id: int, *, for_update: bool = False):
        return cls.query(db_sess, for_update=for_update).filter(cls.id == id).first()

    @classmethod
    def get2(cls, id: int, *, for_update: bool = False, db_sess: Session | None = None):
        """Calls cls.get with db session from global context"""
        from . import get_db_session

        return cls.get(db_sess or get_db_session(), id, for_update=for_update)

    @classmethod
    def all(cls, db_sess: Session, *, for_update: bool = False):
        return cls.query(db_sess, for_update=for_update).all()

    @classmethod
    def all2(cls, *, for_update: bool = False, db_sess: Session | None = None):
        """Calls cls.all with db session from global context"""
        from . import get_db_session

        return cls.all(db_sess or get_db_session(), for_update=for_update)

    def __repr__(self):
        return f"<{self.__class__.__name__}> [{self.id}]"


class ObjMixin(IdMixin):
    """
    Mixin extending `IdMixin` with soft-delete support.

    Adds a `deleted` flag and overrides query helpers to exclude deleted
    rows by default. Provides delete and restore workflows with optional
    hooks for custom logic, audit logging, and actor/context handling.

    Customization:
        - Override `_on_delete(...)` to run custom logic or block deletion.
        Return False to prevent the object from being deleted.
        - Override `_on_restore(...)` to run custom logic or block restore.
        Return False to prevent the object from being restored.
    """

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
    def query2(cls, includeDeleted: bool = False, *, for_update: bool = False, db_sess: Session | None = None):  # pyright: ignore[reportIncompatibleMethodOverride]
        """Calls cls.query with db session from global context"""
        from . import get_db_session

        return cls.query(db_sess or get_db_session(), includeDeleted, for_update=for_update)

    @classmethod
    def get(cls, db_sess: Session, id: int, includeDeleted: bool = False, *, for_update: bool = False):
        return cls.query(db_sess, includeDeleted, for_update=for_update).filter(cls.id == id).first()

    @classmethod
    def get2(cls, id: int, includeDeleted: bool = False, *, for_update: bool = False, db_sess: Session | None = None):
        """Calls cls.get with db session from global context"""
        from . import get_db_session

        return cls.get(db_sess or get_db_session(), id, includeDeleted, for_update=for_update)

    @classmethod
    def all(cls, db_sess: Session, includeDeleted: bool = False, *, for_update: bool = False):  # pyright: ignore[reportIncompatibleMethodOverride]
        return cls.query(db_sess, includeDeleted, for_update=for_update).all()

    @classmethod
    def all2(cls, includeDeleted: bool = False, *, for_update: bool = False, db_sess: Session | None = None):  # pyright: ignore[reportIncompatibleMethodOverride]
        """Calls cls.all with db session from global context"""
        from . import get_db_session

        return cls.all(db_sess or get_db_session(), includeDeleted, for_update=for_update)

    def delete(self, actor: "UserBase", commit: bool = True, now: datetime | None = None, db_sess: Session | None = None):
        from . import Log, get_datetime_now

        now = get_datetime_now() if now is None else now
        db_sess = db_sess if db_sess else actor.db_sess
        if not self._on_delete(db_sess, actor, now, commit):
            return False
        self.deleted = True
        if isinstance(self, TableBase):
            Log.deleted(self, actor, now=now, commit=commit, db_sess=db_sess)
        elif commit:
            db_sess.commit()
        return True

    def delete2(self, commit: bool = True, now: datetime | None = None, *, actor: "UserBase | None" = None, db_sess: Session | None = None):
        """Calls self.delete with UserBase.current as actor"""
        from . import UserBase

        return self.delete(actor or UserBase.current, commit, now, db_sess)

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
        elif commit:
            db_sess.commit()
        return True

    def restore2(self, commit: bool = True, now: datetime | None = None, *, actor: "UserBase | None" = None, db_sess: Session | None = None):
        """Calls self.restore with UserBase.current as actor"""
        from . import UserBase

        return self.restore(actor or UserBase.current, commit, now, db_sess)

    def _on_restore(self, db_sess: Session, actor: "UserBase", now: datetime, commit: bool) -> bool:
        """override to add logic on restore, return True if obj can be restored"""
        return True

    def __repr__(self):
        r = f"<{self.__class__.__name__}> [{self.id}]"
        if self.deleted:
            r += " deleted"
        return r


class SingletonMixin:
    """
    Mixin for tables that must contain exactly one row.

    Provides a `get` method that retrieves the singleton instance or
    creates and initializes it if missing. Intended for global
    configuration or state tables. The `init` method may be overridden
    to perform one-time initialization.
    """

    _ID = 1
    id: Mapped[intpk] = mapped_column(init=False)

    @classmethod
    def get(cls, db_sess: Session, *, commit: bool = True):
        obj = db_sess.get(cls, cls._ID)
        if obj:
            return obj
        obj = cls()
        obj.id = cls._ID
        obj.init()
        db_sess.add(obj)
        if commit:
            db_sess.commit()
        return obj

    @classmethod
    def get2(cls, *, db_sess: Session | None = None, commit: bool = True):
        from . import get_db_session

        return cls.get(db_sess or get_db_session(), commit=commit)

    def init(self):
        pass


T = TypeVar("T", bound="BigIdMixin")


class BigIdMixin:
    """
    Mixin adding a unique, short string identifier (`id_big`).

    Notes:
        - `set_unique_big_id()` should be called when creating a new object
        (before flush/commit) to ensure a unique `id_big` is assigned.
        - If combined with `ObjMixin`, lookups respect soft-deletion
        semantics unless `includeDeleted=True` is specified.
    """

    id_big: Mapped[str] = mapped_column(String(8), unique=True, index=True, init=False)

    @classmethod
    def get_by_big_id(cls: Type[T], id_big: str, includeDeleted: bool = False, *, db_sess: Session | None = None) -> T | None:
        from . import get_db_session

        db_sess = db_sess if db_sess else get_db_session()
        if issubclass(cls, ObjMixin):
            return cls.query(db_sess, includeDeleted).filter(cls.id_big == id_big).first()
        else:
            return db_sess.query(cls).filter(cls.id_big == id_big).first()

    def set_unique_big_id(self, *, db_sess: Session | None = None):
        from . import randstr

        t = self
        while t is not None:
            id_big = randstr(8)
            t = self.get_by_big_id(id_big, includeDeleted=True, db_sess=db_sess)
        self.id_big = id_big  # pyright: ignore[reportPossiblyUnboundVariable]
