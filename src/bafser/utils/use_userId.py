from functools import wraps
from typing import Any, Callable, TypeVar

from flask_jwt_extended import get_jwt_identity, unset_jwt_cookies, verify_jwt_in_request  # type: ignore

from . import response_msg

TFn = TypeVar("TFn", bound=Callable[..., Any])


def use_userId(optional: bool = False):
    from ..authentication import get_user_id_by_jwt_identity

    def decorator(fn: TFn) -> TFn:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            try:
                if optional:
                    verify_jwt_in_request()
                userId = get_user_id_by_jwt_identity(get_jwt_identity())
            except Exception:
                userId = None

            if not optional and userId is None:
                response = response_msg("The JWT has expired")
                unset_jwt_cookies(response)
                return response, 401

            return fn(*args, **kwargs, userId=userId)
        return wrapper  # type: ignore
    return decorator
