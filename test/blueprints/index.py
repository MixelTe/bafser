from flask import Blueprint

from bafser import use_db_session, get_json_values_from_req
from sqlalchemy.orm import Session
from test.data.user import User


blueprint = Blueprint("index", __name__)


@blueprint.route("/api/user")
@use_db_session
def index(db_sess: Session):
    u = User.get_admin(db_sess)
    assert u
    return {"name": u.login}


@blueprint.post("/api/post")
def test_post():  # type: ignore
    a, b, c = get_json_values_from_req(("a", int), ("b", str, "def"), ("c", bool))
    return {"a": a, "b": b, "c": c}  # type: ignore


@blueprint.post("/api/post2")
def test_post2():
    a = get_json_values_from_req(("a", int))
    return {"a": a}
