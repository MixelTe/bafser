from flask import Blueprint

from bafser import Session, use_db_session
from test.data.user import User


blueprint = Blueprint("index", __name__)


@blueprint.get("/ok")
@use_db_session()
def index(db_sess: Session):
    u = User.get_admin(db_sess)
    return {"admin": u.login}
