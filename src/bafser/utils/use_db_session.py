from functools import wraps
from typing import Any, Callable, TypeVar

from flask import g, has_request_context
from sqlalchemy.orm import Session
from typing_extensions import Concatenate, ParamSpec

from .. import db_session

TFn = TypeVar("TFn", bound=Callable[..., Any])


def use_db_session(fn: TFn) -> TFn:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        has_ctx = has_request_context()
        if has_ctx and "db_session" in g and g.db_session is not None:
            return fn(g.db_session, *args, **kwargs)

        with db_session.create_session() as db_sess:
            if has_ctx:
                g.db_session = db_sess
            try:
                return fn(*args, **kwargs, db_sess=db_sess)
            finally:
                if has_ctx:
                    delattr(g, "db_session")

    return wrapper  # type: ignore


P = ParamSpec("P")
R = TypeVar("R")


def use_db_sess(fn: Callable[Concatenate[Session, P], R]) -> Callable[P, R]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        has_ctx = has_request_context()
        if has_ctx and "db_session" in g and g.db_session is not None:
            return fn(g.db_session, *args, **kwargs)

        with db_session.create_session() as db_sess:
            if has_ctx:
                g.db_session = db_sess
            try:
                return fn(db_sess, *args, **kwargs)
            finally:
                if has_ctx:
                    delattr(g, "db_session")

    return wrapper
