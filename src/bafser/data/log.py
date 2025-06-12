from datetime import datetime
from typing import Any, Union

from sqlalchemy import Column, DateTime, orm, Integer, String, JSON
from sqlalchemy.orm import Session

from .. import SqlAlchemyBase, TableBase, UserBase, IdMixin, get_datetime_now

FieldName = str
NewValue = Any
OldValue = Any


class Log(SqlAlchemyBase, IdMixin):
    __tablename__ = "Log"

    date = Column(DateTime, nullable=False)
    actionCode = Column(String(16), nullable=False)
    userId = Column(Integer, nullable=False)
    userName = Column(String(64), nullable=False)
    tableName = Column(String(16), nullable=False)
    recordId = Column(Integer, nullable=False)
    changes = Column(JSON, nullable=False)

    def __repr__(self):
        return f"<Log> [{self.id}] {self.date} {self.actionCode}"

    def get_dict(self):
        return self.to_dict(only=("id", "date", "actionCode", "userId", "userName", "tableName", "recordId", "changes"))

    @staticmethod
    def added(
        record: TableBase,
        actor: Union[UserBase, None],
        changes: list[tuple[FieldName, NewValue]],
        now: datetime = None,
        commit=True,
        db_sess: Session = None,
    ):
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else Session.object_session(actor)
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
            if record.id is not None:
                log.recordId = record.id
            elif commit:
                db_sess.commit()
                log.recordId = record.id
        if commit:
            db_sess.commit()
        return log

    @staticmethod
    def updated(
        record: TableBase,
        actor: Union[UserBase, None],
        changes: list[tuple[FieldName, OldValue, NewValue]],
        now: datetime = None,
        commit=True,
        db_sess: Session = None,
    ):
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else Session.object_session(actor)
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
        record: TableBase,
        actor: Union[UserBase, None],
        changes: list[tuple[FieldName, OldValue]] = [],
        now: datetime = None,
        commit=True,
        db_sess: Session = None,
    ):
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else Session.object_session(actor)
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
        record: TableBase,
        actor: Union[UserBase, None],
        changes: list[tuple[FieldName, OldValue, NewValue]] = [],
        now: datetime = None,
        commit=True,
        db_sess: Session = None,
    ):
        if actor is None:
            actor = UserBase.get_fake_system()
        db_sess = db_sess if db_sess else Session.object_session(actor)
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


class Actions:
    added = "added"
    updated = "updated"
    deleted = "deleted"
    restored = "restored"
