from flask import Blueprint
from flask_jwt_extended import jwt_required  # type: ignore

from bafser import permission_required, response_msg, use_db_session, get_json_values_from_req, use_user
from sqlalchemy.orm import Session
from bafser.doc_api import doc_api, get_api_docs
from test.data import Operations
from test.data.img import Img, ImageJson
from test.data.user import User


blueprint = Blueprint("index", __name__)


@blueprint.route("/api")
def docs():
    return get_api_docs()


@blueprint.route("/api/user")
@doc_api(res=dict)
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
@doc_api(req=dict, res=list, desc="The best route")
def test_post2():
    a = get_json_values_from_req(("a", int))
    return {"a": a}


@blueprint.post("/api/img")
@doc_api(req=ImageJson)
@jwt_required()
@use_db_session
@use_user()
@permission_required(Operations.upload_img)
def upload_img(db_sess: Session, user: User):
    img_data = get_json_values_from_req(("img", ImageJson))

    img, image_error = Img.new(user, img_data)
    if image_error:
        return response_msg(image_error, 400)
    assert img

    return {"id": img.id}
