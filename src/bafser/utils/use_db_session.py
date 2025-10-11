from functools import wraps
from typing import Any, Callable, TypeVar

from sqlalchemy.orm import Session
from typing_extensions import Concatenate, ParamSpec

from .. import db_session

TFn = TypeVar("TFn", bound=Callable[..., Any])


def use_db_session(fn: TFn) -> TFn:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        with db_session.create_session() as db_sess:
            return fn(*args, **kwargs, db_sess=db_sess)
    return wrapper  # type: ignore


P = ParamSpec("P")
R = TypeVar("R")


def use_db_sess(fn: Callable[Concatenate[Session, P], R]) -> Callable[P, R]:
    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with db_session.create_session() as db_sess:
            return fn(db_sess, *args, **kwargs)
    return wrapper
