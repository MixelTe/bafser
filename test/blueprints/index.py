from flask import Blueprint

from bafser import use_db_session
from sqlalchemy.orm import Session
from test.data.user import User


blueprint = Blueprint("index", __name__)


@blueprint.get("/api/user")
@use_db_session()
def index(db_sess: Session):
    u = User.get_admin(db_sess)
    return {"name": u.login}
