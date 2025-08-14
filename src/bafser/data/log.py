from datetime import datetime
from typing import Any, TypedDict

from sqlalchemy import String, JSON
from sqlalchemy.orm import Session, Mapped, mapped_column

from .. import SqlAlchemyBase, UserBase, IdMixin, get_datetime_now

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
        return f"<Log> [{self.id}] {self.date} {self.actionCode}"

    def get_dict(self) -> LogDict:
        return self.to_dict(only=("id", "date", "actionCode", "userId", "userName", "tableName", "recordId", "changes"))  # type: ignore

    @staticmethod
    def added(
        record: SqlAlchemyBase,
        actor: UserBase | None,
        changes: list[tuple[FieldName, NewValue]],
        now: datetime | None = None,
        commit: bool = True,
        db_sess: Session | None = None,
    ):
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else Session.object_session(actor)
        assert db_sess
        if now is None:
            now = get_datetime_now()
        log = Log(
            date=now,
            actionCode=Actions.added,
            userId=actor.id,
            userName=actor.name,
            tableName=record.__tablename__,
            recordId=-1,
            changes=list(map(lambda v: (v[0], None, v[1]), changes))
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
        changes: Changes,
        now: datetime | None = None,
        commit: bool = True,
        db_sess: Session | None = None,
    ):
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else Session.object_session(actor)
        assert db_sess
        if now is None:
            now = get_datetime_now()
        log = Log(
            date=now,
            actionCode=Actions.updated,
            userId=actor.id,
            userName=actor.name,
            tableName=record.__tablename__,
            recordId=record.id if isinstance(record, IdMixin) else -1,
            changes=changes
        )
        db_sess.add(log)
        if commit:
            db_sess.commit()
        return log

    @staticmethod
    def deleted(
        record: SqlAlchemyBase,
        actor: UserBase | None,
        changes: list[tuple[FieldName, OldValue]] = [],
        now: datetime | None = None,
        commit: bool = True,
        db_sess: Session | None = None,
    ):
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else Session.object_session(actor)
        assert db_sess
        if now is None:
            now = get_datetime_now()
        log = Log(
            date=now,
            actionCode=Actions.deleted,
            userId=actor.id,
            userName=actor.name,
            tableName=record.__tablename__,
            recordId=record.id if isinstance(record, IdMixin) else -1,
            changes=list(map(lambda v: (v[0], v[1], None), changes))
        )
        db_sess.add(log)
        if commit:
            db_sess.commit()
        return log

    @staticmethod
    def restored(
        record: SqlAlchemyBase,
        actor: UserBase | None,
        changes: Changes = [],
        now: datetime | None = None,
        commit: bool = True,
        db_sess: Session | None = None,
    ):
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else Session.object_session(actor)
        assert db_sess
        if now is None:
            now = get_datetime_now()
        log = Log(
            date=now,
            actionCode=Actions.restored,
            userId=actor.id,
            userName=actor.name,
            tableName=record.__tablename__,
            recordId=record.id if isinstance(record, IdMixin) else -1,
            changes=changes
        )
        db_sess.add(log)
        if commit:
            db_sess.commit()
        return log
