from functools import wraps
from flask import abort
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from sqlalchemy.orm import Session


def use_user_optional():
    from ..data.user import get_user_table

    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            if "db_sess" not in kwargs:
                abort(500, "use_user_optional: no db_sess")
            db_sess: Session = kwargs["db_sess"]

            try:
                verify_jwt_in_request()
                jwt_identity = get_jwt_identity()
                if (not isinstance(jwt_identity, list) and not isinstance(jwt_identity, tuple)) or len(jwt_identity) != 2:
                    raise Exception()

                user = get_user_table().get(db_sess, jwt_identity[0])
                if not user:
                    raise Exception()
                if user.password != jwt_identity[1]:
                    raise Exception()
            except Exception:
                user = None

            return fn(*args, **kwargs, user=user)

        return decorator

    return wrapper
