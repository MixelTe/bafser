from functools import wraps
from typing import Any, Callable, TypeVar

from flask import g
from flask_jwt_extended import unset_jwt_cookies  # type: ignore
from typing_extensions import deprecated

from . import response_msg

TFn = TypeVar("TFn", bound=Callable[..., Any])


@deprecated("Use get_userId_required or get_userId instead")
def use_userId(optional: bool = False):
    def decorator(fn: TFn) -> TFn:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            userId = g.userId
            if not optional and userId is None:
                response = response_msg("The JWT has expired")
                unset_jwt_cookies(response)
                return response, 401

            return fn(*args, **kwargs, userId=userId)
        return wrapper  # type: ignore
    return decorator
