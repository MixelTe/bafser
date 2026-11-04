from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, event, inspect, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session, SessionTransaction

if TYPE_CHECKING:
    from ..db_session import SqlAlchemyBase


_TRANSACTION_FILES = "bafser.pending_transaction_files"


@dataclass
class _CreatedFile:
    path: str
    query: Select[Any]
    engine: Engine
    verify: bool = False


@dataclass
class _FileTransaction:
    files: list[_CreatedFile] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    commit_attempted: bool = False


def track_created_file(record: SqlAlchemyBase, path: str) -> None:
    """Track an exclusively created file owned by a flushed ORM record.

    Call after opening the new path with ``xb``, before writing. Ordinary
    rollback/close removes it. An ambiguous COMMIT is checked with a fresh
    transaction; if the database cannot establish the outcome, retain the file
    and log its path for reconciliation. Existing files must never be tracked.
    Transactions must be owned by an Engine-bound Session, not managed through
    an external Connection transaction.
    """
    state = inspect(record)
    session = state.session
    if session is None or state.identity is None:
        raise ValueError("track_created_file requires a flushed record in a Session")
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None:
        raise ValueError("track_created_file requires an active transaction")
    bind = session.get_bind(mapper=state.mapper)
    engine = bind.engine if isinstance(bind, Connection) else bind
    query = (
        select(1)
        .select_from(state.mapper.persist_selectable)
        .where(*(column == value for column, value in zip(state.mapper.primary_key, state.identity)))
    )
    pending: dict[SessionTransaction, _FileTransaction] = session.info.setdefault(_TRANSACTION_FILES, {})
    pending.setdefault(transaction, _FileTransaction()).files.append(_CreatedFile(path, query, engine))


@event.listens_for(Session, "before_commit")
def _prepare_file_commit(session: Session) -> None:
    transaction = session.get_nested_transaction() or session.get_transaction()
    pending: dict[SessionTransaction, _FileTransaction] = session.info.get(_TRANSACTION_FILES, {})
    if transaction in pending:
        pending[transaction].commit_attempted = True


@event.listens_for(Session, "after_commit")
def _commit_created_files(session: Session) -> None:
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None:
        return
    pending: dict[SessionTransaction, _FileTransaction] = session.info.get(_TRANSACTION_FILES, {})
    tracked = pending.pop(transaction, None)
    if tracked is not None:
        if transaction.parent is not None:
            pending.setdefault(transaction.parent, _FileTransaction()).files.extend(tracked.files)
        else:
            # A failed SAVEPOINT release can leave an uncertain file in the
            # outer transaction. Confirm those rows only after the outer write
            # transaction ends, even if its COMMIT succeeds.
            uncertain = [file_record for file_record in tracked.files if file_record.verify]
            if uncertain:
                tracked.files = uncertain
                pending[transaction] = tracked
    if not pending:
        session.info.pop(_TRANSACTION_FILES, None)


@event.listens_for(Session, "after_transaction_end")
def _discard_created_files(session: Session, transaction: SessionTransaction) -> None:
    pending: dict[SessionTransaction, _FileTransaction] = session.info.get(_TRANSACTION_FILES, {})
    tracked = pending.pop(transaction, None)
    if tracked is None:
        return
    for file_record in tracked.files:
        if tracked.commit_attempted:
            file_record.verify = True
        if file_record.verify and transaction.parent is not None:
            # Probing before the outer transaction ends could block on its own
            # writes or see an intermediate state. Defer to the parent instead.
            pending.setdefault(transaction.parent, _FileTransaction()).files.append(file_record)
            continue
        if file_record.verify:
            try:
                # COMMIT may have succeeded before the client lost its response.
                # A fresh connection/transaction must establish the outcome;
                # rollback on the original Session cannot establish it.
                with file_record.engine.connect() as connection:
                    exists = connection.execute(file_record.query).first() is not None
                if exists:
                    continue
            except Exception:
                logging.exception("Could not establish file commit outcome; retaining file %s for reconciliation", file_record.path)
                continue
        try:
            os.remove(file_record.path)
        except FileNotFoundError:
            pass
        except OSError:
            logging.exception("Could not remove rolled-back file %s", file_record.path)
    if not pending:
        session.info.pop(_TRANSACTION_FILES, None)
