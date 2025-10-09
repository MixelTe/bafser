from flask import g
from sqlalchemy.orm import Session


def get_db_session() -> Session:
    from .. import db_session
    if "db_session" not in g:
        g.db_session = db_session.create_session()
    return g.db_session
