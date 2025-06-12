from functools import wraps
from flask import abort
from flask_jwt_extended import get_jwt_identity, unset_jwt_cookies
from sqlalchemy.orm import Session

from . import response_msg


def use_user():
    from ..data.user import get_user_table

    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            if "db_sess" not in kwargs:
                abort(500, "use_user: no db_sess")
            db_sess: Session = kwargs["db_sess"]

            jwt_identity = get_jwt_identity()
            if (not isinstance(jwt_identity, list) and not isinstance(jwt_identity, tuple)) or len(jwt_identity) != 2:
                response = response_msg("The JWT has expired")
                unset_jwt_cookies(response)
                return response, 401

            user = get_user_table().get(db_sess, jwt_identity[0])
            if not user:
                return response_msg("User not found"), 401
            if user.password != jwt_identity[1]:
                response = response_msg("The JWT has expired")
                unset_jwt_cookies(response)
                return response, 401

            return fn(*args, **kwargs, user=user)

        return decorator

    return wrapper
