from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session
from sqlalchemy_serializer import SerializerMixin
import sqlalchemy as sa

if TYPE_CHECKING:
    from . import UserBase


class TableBase(SerializerMixin):
    __table_args__ = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}

    if TYPE_CHECKING:
        __tablename__: str

    def __repr__(self):
        return f"<{self.__class__.__name__}>"

    def get_dict(self):
        return {}


class IdMixin:
    id = sa.Column(sa.Integer, primary_key=True, unique=True, autoincrement=True)

    @classmethod
    def get(cls, db_sess: Session, id: int):
        return db_sess.get(cls, id)

    @classmethod
    def all(cls, db_sess: Session):
        return db_sess.query(cls).all()

    def __repr__(self):
        return f"<{self.__class__.__name__}> [{self.id}]"


class ObjMixin(IdMixin):
    deleted = sa.Column(sa.Boolean, sa.DefaultClause("0"), nullable=False)

    @classmethod
    def query(cls, db_sess: Session, includeDeleted=False):
        items = db_sess.query(cls)
        if not includeDeleted:
            items = items.filter(cls.deleted == False)
        return items

    @classmethod
    def get(cls, db_sess: Session, id: int, includeDeleted=False):
        obj = db_sess.get(cls, id)
        if obj is None or (not includeDeleted and obj.deleted):
            return None
        return obj

    @classmethod
    def all(cls, db_sess: Session, includeDeleted=False):
        return cls.query(db_sess, includeDeleted).all()

    def delete(self, actor: "UserBase", commit=True, now: datetime = None, db_sess: Session = None):
        from . import Log
        self.deleted = True
        Log.deleted(self, actor, now=now, commit=commit, db_sess=db_sess)

    def restore(self, actor: "UserBase", commit=True, now: datetime = None, db_sess: Session = None):
        from . import Log
        self.deleted = False
        Log.restored(self, actor, now=now, commit=commit, db_sess=db_sess)
