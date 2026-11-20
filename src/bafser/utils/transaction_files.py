"""Keep newly created files consistent with their owning database transaction.

Successful commit retains a file; rollback removes it. If a COMMIT outcome cannot
be verified, retain the file and log file_commit_outcome_unknown. A failed removal
logs file_rollback_removal_failed. Neither event proves that deletion is safe.

By default diagnostics contain the event, row/model identity, path fingerprint,
full tracked path and traceback. LOG_ERROR_DETAILS=False in production omits the
path/exception values even from the source LogRecord seen by host handlers.
To locate a file in that reduced mode, use the row's path builder or known storage
candidates and compare sha256(path.encode("utf8", "surrogatepass")).hexdigest()[:24].
Hash the exact original path string, not file contents or a normalized path.
After database recovery, reconcile its row/reference before removing a file.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
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
    log_reference: str
    verify: bool = False


@dataclass
class _FileTransaction:
    files: list[_CreatedFile] = field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    commit_attempted: bool = False


def _file_log_reference(path: str, model_name: str, identity: tuple[Any, ...]) -> str:
    # Paths and string keys can contain secrets. A reproducible fingerprint lets
    # operators match a retained file without exposing its directory or basename.
    reference = "[omitted]"
    if type(path) is str and len(path) <= 32768:
        reference = hashlib.sha256(path.encode("utf8", errors="surrogatepass")).hexdigest()[:24]
    if len(model_name) > 64 or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", model_name) is None:
        model_name = "[omitted]"
    key = "[omitted]"
    if len(identity) <= 4 and all(type(value) is int and value.bit_length() <= 64 for value in identity):
        key = ",".join(str(value) for value in identity)
    return f"ref={reference} row={model_name}:{key}"


def _log_file_error(file_record: _CreatedFile, error: Exception, *, outcome_unknown: bool) -> None:
    from ..logger import log_error_details

    event_name = "file_commit_outcome_unknown" if outcome_unknown else "file_rollback_removal_failed"
    if log_error_details():
        message = (
            "Could not establish file commit outcome; retaining file %s for reconciliation"
            if outcome_unknown
            else "Could not remove rolled-back file %s"
        )
        logging.error(
            "%s %s; " + message,
            event_name,
            file_record.log_reference,
            file_record.path,
            exc_info=(type(error), error, error.__traceback__),
        )
        return

    # A host handler may use a plain formatter. Keep raw paths, exception values
    # and traceback objects out of the reduced-mode LogRecord itself.
    exception_type = type(error).__name__
    if len(exception_type) > 64 or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", exception_type) is None:
        exception_type = "Exception"
    detail = "; retaining file for reconciliation" if outcome_unknown else ""
    logging.error(
        "%s %s error=%s%s",
        event_name,
        file_record.log_reference,
        exception_type,
        detail,
        extra={"bafser_safe_message": True},
    )


def track_created_file(record: SqlAlchemyBase, path: str) -> None:
    """Track an exclusively created file owned by a flushed ORM record.

    Call after opening the new path with ``xb``, before writing. Ordinary
    rollback/close removes it. An ambiguous COMMIT is checked with a fresh
    transaction; if the database cannot establish the outcome, retain the file
    and log its path for reconciliation (a file/row reference in reduced mode).
    Existing files must never be tracked.
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
    reference = _file_log_reference(path, state.mapper.class_.__name__, state.identity)
    pending.setdefault(transaction, _FileTransaction()).files.append(_CreatedFile(path, query, engine, reference))


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
            except Exception as error:
                _log_file_error(file_record, error, outcome_unknown=True)
                continue
        try:
            os.remove(file_record.path)
        except FileNotFoundError:
            pass
        except OSError as error:
            _log_file_error(file_record, error, outcome_unknown=False)
    if not pending:
        session.info.pop(_TRANSACTION_FILES, None)
