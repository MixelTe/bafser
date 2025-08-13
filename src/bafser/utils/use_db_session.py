from functools import wraps
from typing import Any, Callable, TypeVar

from .. import db_session


TFn = TypeVar("TFn", bound=Callable[..., Any])


def use_db_session(fn: TFn) -> TFn:
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any):
        with db_session.create_session() as db_sess:
            return fn(*args, **kwargs, db_sess=db_sess)
    return wrapper  # type: ignore
