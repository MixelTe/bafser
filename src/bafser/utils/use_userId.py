from functools import wraps
from flask_jwt_extended import get_jwt_identity, unset_jwt_cookies

from . import response_msg


def use_userId():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            jwt_identity = get_jwt_identity()
            if (not isinstance(jwt_identity, list) and not isinstance(jwt_identity, tuple)) or len(jwt_identity) != 2:
                response = response_msg("The JWT has expired")
                unset_jwt_cookies(response)
                return response, 401

            userId = jwt_identity[0]
            return fn(*args, **kwargs, userId=userId)

        return decorator

    return wrapper


def use_userId_optional():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            try:
                jwt_identity = get_jwt_identity()
                if (not isinstance(jwt_identity, list) and not isinstance(jwt_identity, tuple)) or len(jwt_identity) != 2:
                    response = response_msg("The JWT has expired")
                    unset_jwt_cookies(response)
                    return response, 401
                userId = jwt_identity[0]
            except Exception:
                userId = None

            return fn(*args, **kwargs, userId=userId)

        return decorator

    return wrapper
