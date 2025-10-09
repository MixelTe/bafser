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
        actor: UserBase | None = None,
        changes: list[tuple[FieldName, NewValue]] | None = None,
        now: datetime | None = None,
        commit: bool = True,
        db_sess: Session | None = None,
    ):
        _changes = None
        if changes is not None:
            _changes = [(key, None, v) for key, v in changes]
        log = Log._create(record, actor, _changes, now, False, db_sess, Actions.added)
        db_sess = log.db_sess
        db_sess.add(record)
        if commit:
            if isinstance(record, IdMixin):
                if record.id is None:  # pyright: ignore[reportUnnecessaryComparison]
                    db_sess.commit()
                    log.recordId = record.id
            db_sess.commit()
        return log

    @staticmethod
    def updated(
        record: SqlAlchemyBase,
        actor: UserBase | None = None,
        changes: Changes | None = None,
        now: datetime | None = None,
        commit: bool = True,
        db_sess: Session | None = None,
    ):
        return Log._create(record, actor, changes, now, commit, db_sess, Actions.updated)

    @staticmethod
    def deleted(
        record: SqlAlchemyBase,
        actor: UserBase | None = None,
        changes: list[tuple[FieldName, OldValue]] | None = None,
        now: datetime | None = None,
        commit: bool = True,
        db_sess: Session | None = None,
    ):
        _changes = None
        if changes is not None:
            _changes = [(key, v, None) for key, v in changes]
        return Log._create(record, actor, _changes, now, commit, db_sess, Actions.deleted)

    @staticmethod
    def restored(
        record: SqlAlchemyBase,
        actor: UserBase | None = None,
        changes: Changes | None = None,
        now: datetime | None = None,
        commit: bool = True,
        db_sess: Session | None = None,
    ):
        return Log._create(record, actor, changes, now, commit, db_sess, Actions.restored)

    @staticmethod
    def _create(
        record: SqlAlchemyBase,
        actor: UserBase | None,
        changes: Changes | None,
        now: datetime | None,
        commit: bool,
        db_sess: Session | None,
        actionCode: str,
    ):
        if actor is None:
            actor = UserBase.get_current(lazyload=True)
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else actor.db_sess
        if now is None:
            now = get_datetime_now()
        if changes is None:
            changes = Log._get_obj_changes(record)
        log = Log(
            date=now,
            actionCode=actionCode,
            userId=actor.id,
            userName=actor.name,
            tableName=record.__tablename__,
            recordId=record.id if isinstance(record, IdMixin) and record.id is not None else -1,  # pyright: ignore[reportUnnecessaryComparison]
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
