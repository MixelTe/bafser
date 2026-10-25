"""Transaction-scoped tracking for bafser's explicit FOR UPDATE queries."""

from typing import Any, TypeVar
from weakref import ref

from sqlalchemy import event, inspect
from sqlalchemy.orm import ORMExecuteState, Query, Session, SessionTransaction

import bafser_config

T = TypeVar("T")
_QUERY_KEY = "_bafser_for_update_model"
_MARK_KEY = "_bafser_for_update"
_EPOCH_KEY = "_bafser_for_update_epoch"


class ForUpdateRequiredError(RuntimeError):
    """The object was not locked through bafser in its current transaction."""


class LockNotSupportedError(RuntimeError):
    """The bound database cannot provide bafser's FOR UPDATE contract."""


def for_update_query(query: Query[T], model: type[T]) -> Query[T]:
    return query.with_for_update().populate_existing().execution_options(**{_QUERY_KEY: model})


def is_for_update(obj: object) -> bool:
    state = inspect(obj)
    if state is None:
        return False
    session = state.session
    mark = state.info.get(_MARK_KEY)
    if session is None or not state.persistent or mark is None:
        return False
    session_ref, transaction_ref, epoch = mark
    transaction = session.get_transaction()
    return bool(
        session_ref() is session
        and transaction is not None
        and transaction_ref() is transaction
        and transaction.is_active
        and session.info.get(_EPOCH_KEY) is epoch
    )


def _invoke_statement(execute_state: ORMExecuteState) -> Any:
    try:
        return execute_state.invoke_statement()
    except Exception:
        # A deadlock can roll back the database transaction before SQLAlchemy
        # observes that rollback. Never trust earlier marks after an SQL error.
        execute_state.session.info.pop(_EPOCH_KEY, None)
        raise


@event.listens_for(Session, "do_orm_execute")
def _track_for_update(execute_state: ORMExecuteState) -> Any:
    model = execute_state.execution_options.get(_QUERY_KEY)
    if model is None or not execute_state.is_select or execute_state.is_relationship_load or execute_state.is_column_load:
        if _EPOCH_KEY in execute_state.session.info:
            return _invoke_statement(execute_state)
        return None

    session = execute_state.session
    bind = session.get_bind(**execute_state.bind_arguments)
    if bind.dialect.name not in {"mysql", "mariadb", "postgresql", "oracle"}:
        if not getattr(bafser_config, "allow_unsupported_for_update_clause", False):
            raise LockNotSupportedError(f"FOR UPDATE is not supported for {bind.dialect.name}")

    # Only explicitly selected instances of the helper's model are tracked.
    # Joined/eager relationships and scalar projections must not inherit a mark.
    statement = execute_state.statement
    columns = getattr(statement, "column_descriptions", ())
    indexes = [index for index, column in enumerate(columns) if column.get("expr") is model]
    lock = getattr(statement, "_for_update_arg", None)
    if indexes and (lock is None or lock.read or lock.key_share or lock.of is not None):
        raise ValueError("Tracked queries require an unmodified exclusive FOR UPDATE clause")

    execute_state.update_execution_options(populate_existing=True)
    result = _invoke_statement(execute_state)
    if not indexes:
        return result

    transaction = session.get_transaction()
    epoch = session.info.setdefault(_EPOCH_KEY, object())
    # Buffer before marking: failed SQL/result loading must never leave marks.
    # FrozenResult preserves ORM result metadata used by Query.first/all/iteration.
    try:
        frozen = result.freeze()
    except Exception:
        session.info.pop(_EPOCH_KEY, None)
        raise
    finally:
        result.close()
    if transaction is not None and transaction.is_active and session.get_transaction() is transaction and session.info.get(_EPOCH_KEY) is epoch:
        mark = (ref(session), ref(transaction), epoch)
        for row in frozen():
            for index in indexes:
                obj = row[index]
                if obj is not None:
                    state = inspect(obj)
                    if state is not None and state.session is session and state.persistent:
                        state.info[_MARK_KEY] = mark
    return frozen()


@event.listens_for(Session, "after_transaction_end")
def _transaction_ended(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is None:
        session.info.pop(_EPOCH_KEY, None)


@event.listens_for(Session, "after_soft_rollback")
def _transaction_rolled_back(session: Session, previous_transaction: SessionTransaction) -> None:
    # Conservatively invalidate every mark, including after SAVEPOINT rollback.
    session.info.pop(_EPOCH_KEY, None)


@event.listens_for(Session, "persistent_to_detached")
@event.listens_for(Session, "persistent_to_transient")
def _object_detached(session: Session, obj: object) -> None:
    state = inspect(obj)
    if state is not None:
        state.info.pop(_MARK_KEY, None)
