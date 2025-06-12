from functools import wraps
from bafser import db_session


def use_db_session():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            db_sess = db_session.create_session()
            try:
                return fn(*args, **kwargs, db_sess=db_sess)
            finally:
                db_sess.close()

        return decorator

    return wrapper
