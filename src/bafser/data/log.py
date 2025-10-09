from datetime import datetime
from typing import Any, TypedDict

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.orm.attributes import get_history

from .. import IdMixin, SqlAlchemyBase, UserBase, get_datetime_now

FieldName = str
NewValue = Any
OldValue = Any
Changes = list[tuple[FieldName, OldValue, NewValue]]


class Actions:
    added = "added"
    updated = "updated"
    deleted = "deleted"
    restored = "restored"


class LogDict(TypedDict):
    id: int
    date: datetime
    actionCode: str
    userId: int
    userName: str
    tableName: str
    recordId: int
    changes: Changes


class Log(SqlAlchemyBase, IdMixin):
    __tablename__ = "Log"

    date: Mapped[datetime]
    actionCode: Mapped[str] = mapped_column(String(16))
    userId: Mapped[int]
    userName: Mapped[str] = mapped_column(String(64))
    tableName: Mapped[str] = mapped_column(String(16))
    recordId: Mapped[int]
    changes: Mapped[Changes] = mapped_column(JSON)

    def __repr__(self):
        return f"<Log> [{self.id}] {self.date} {self.actionCode} {self.tableName}[{self.recordId}]"

    def get_dict(self) -> LogDict:
        return self.to_dict(only=("id", "date", "actionCode", "userId", "userName", "tableName", "recordId", "changes"))  # type: ignore

    @staticmethod
    def added(
        record: SqlAlchemyBase,
        actor: UserBase | None,
        changes: list[tuple[FieldName, NewValue]] | None = None,
        now: datetime | None = None,
        commit: bool = True,
        db_sess: Session | None = None,
    ):
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else actor.db_sess
        if now is None:
            now = get_datetime_now()
        if changes is None:
            _changes = Log._get_obj_changes(record)
        else:
            _changes = [(key, None, v) for key, v in changes]
        log = Log(
            date=now,
            actionCode=Actions.added,
            userId=actor.id,
            userName=actor.name,
            tableName=record.__tablename__,
            recordId=-1,
            changes=Log._serialize_changes(_changes)
        )
        db_sess.add(log)
        if isinstance(record, IdMixin):
            if record.id is not None:  # type: ignore
                log.recordId = record.id
            elif commit:
                db_sess.commit()
                log.recordId = record.id
        if commit:
            db_sess.commit()
        return log

    @staticmethod
    def updated(
        record: SqlAlchemyBase,
        actor: UserBase | None,
        changes: Changes | None = None,
        now: datetime | None = None,
        commit: bool = True,
        db_sess: Session | None = None,
    ):
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else actor.db_sess
        if now is None:
            now = get_datetime_now()
        if changes is None:
            changes = Log._get_obj_changes(record)
        log = Log(
            date=now,
            actionCode=Actions.updated,
            userId=actor.id,
            userName=actor.name,
            tableName=record.__tablename__,
            recordId=record.id if isinstance(record, IdMixin) else -1,
            changes=Log._serialize_changes(changes)
        )
        db_sess.add(log)
        if commit:
            db_sess.commit()
        return log

    @staticmethod
    def deleted(
        record: SqlAlchemyBase,
        actor: UserBase | None,
        changes: list[tuple[FieldName, OldValue]] | None = None,
        now: datetime | None = None,
        commit: bool = True,
        db_sess: Session | None = None,
    ):
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else actor.db_sess
        if now is None:
            now = get_datetime_now()
        if changes is None:
            _changes = Log._get_obj_changes(record)
        else:
            _changes = [(key, v, None) for key, v in changes]
        log = Log(
            date=now,
            actionCode=Actions.deleted,
            userId=actor.id,
            userName=actor.name,
            tableName=record.__tablename__,
            recordId=record.id if isinstance(record, IdMixin) else -1,
            changes=Log._serialize_changes(_changes)
        )
        db_sess.add(log)
        if commit:
            db_sess.commit()
        return log

    @staticmethod
    def restored(
        record: SqlAlchemyBase,
        actor: UserBase | None,
        changes: Changes | None = None,
        now: datetime | None = None,
        commit: bool = True,
        db_sess: Session | None = None,
    ):
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else actor.db_sess
        if now is None:
            now = get_datetime_now()
        if changes is None:
            changes = Log._get_obj_changes(record)
        log = Log(
            date=now,
            actionCode=Actions.restored,
            userId=actor.id,
            userName=actor.name,
            tableName=record.__tablename__,
            recordId=record.id if isinstance(record, IdMixin) else -1,
            changes=Log._serialize_changes(changes)
        )
        db_sess.add(log)
        if commit:
            db_sess.commit()
        return log

    @staticmethod
    def _serialize(v: Any):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    @staticmethod
    def _serialize_changes(changes: Changes) -> Changes:
        return [(key, Log._serialize(old), Log._serialize(new)) for key, old, new in changes]

    @staticmethod
    def _get_obj_changes(obj: SqlAlchemyBase):
        changes: Changes = []
        for attr in obj.__mapper__.columns:
            hist = get_history(obj, attr.key)
            if hist.has_changes():
                old = hist.deleted[0] if hist.deleted else None
                new = hist.added[0] if hist.added else None
                if old != new:
                    if attr.key in obj.__fields_hidden_in_log__:
                        old = "***" if old else None
                        new = "***" if new else None
                    changes.append((attr.key, old, new))
        return changes
