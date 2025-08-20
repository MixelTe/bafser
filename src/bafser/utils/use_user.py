from functools import wraps
from typing import Any, Callable, TypeVar

from flask import abort
from flask_jwt_extended import get_jwt_identity, unset_jwt_cookies, verify_jwt_in_request  # type: ignore
from sqlalchemy.orm import Session

from . import response_msg

TFn = TypeVar("TFn", bound=Callable[..., Any])


def use_user(*, optional: bool = False, lazyload: bool = False, for_update: bool = False):
    from ..authentication import get_user_by_jwt_identity

    def decorator(fn: TFn) -> TFn:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            if "db_sess" not in kwargs:
                abort(500, "use_user: no db_sess")
            db_sess: Session = kwargs["db_sess"]

            try:
                if optional:
                    verify_jwt_in_request()
                user = get_user_by_jwt_identity(db_sess, get_jwt_identity(), lazyload=lazyload, for_update=for_update)
            except Exception:
                user = None

            if not optional and user is None:
                response = response_msg("The JWT has expired")
                unset_jwt_cookies(response)
                return response, 401

            return fn(*args, **kwargs, user=user)
        return wrapper  # type: ignore
    return decorator
