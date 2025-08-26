from typing import Literal, NotRequired, TypedDict
from flask import Blueprint, send_from_directory
from flask_jwt_extended import jwt_required  # type: ignore

from bafser import JsonObj, JsonOpt, permission_required, response_msg, use_db_session, get_json_values_from_req, use_user
from sqlalchemy.orm import Session
from bafser.doc_api import doc_api, get_api_docs
from test.data import Operations
from test.data.img import Img, ImageJson
from test.data.user import User
import bafser_config


blueprint = Blueprint("index", __name__)


@blueprint.route("/api")
def docs():
    return get_api_docs()


@blueprint.route("/")
def index():
    return send_from_directory(bafser_config.blueprints_folder, "index.html")


@blueprint.route("/api/user")
# @doc_api(res=UserDict)
@use_db_session
def user(db_sess: Session):
    u = User.get_admin(db_sess)
    assert u
    return u.get_dict()


class SomeDict2(TypedDict):
    value: int
    isCool: NotRequired[bool]


class SomeDict(TypedDict):
    name: str
    keys: list[int | str]
    v: list[SomeDict2]


@blueprint.post("/api/post")
def test_post():  # type: ignore
    a, b, c, d, e, f, g, h = get_json_values_from_req(("a", int), ("b", str, "def"), ("c", bool), ("d", list, []),  # type: ignore
                                                      ("e", list[int], []), ("f", dict, {}), ("g", dict[str, int], {}), ("h", SomeDict))
    return {"a": a, "b": b, "c": c, "d": d, "e": e, "f": f, "g": g, "h": h}  # type: ignore


class SomeObj2(JsonObj):
    value: int
    isCool: JsonOpt[bool]


class SomeObj(JsonObj):
    name: str
    keys: list[int | str]
    v: list[list[SomeObj2]]


class SomeDict11(TypedDict):
    name: str
    keys: list[int | str]
    v: list[list[SomeObj2]]


class SomeObjRes(JsonObj):
    a: int
    obj: SomeDict11


@blueprint.post("/api/post2")
@doc_api(req=dict, res=list, desc="The best route")
def test_post2():  # type: ignore
    a, obj = get_json_values_from_req(("a", int), ("obj", SomeDict11))
    return SomeObjRes.new(a=a, obj=obj).json()


class SomeObj3(JsonObj):
    name: Literal["3"]
    v: int


class SomeObj4(JsonObj):
    name = Literal["4"]
    d: str


class SomeObj5(JsonObj):
    objs: list[SomeObj3 | SomeObj4]


@blueprint.post("/api/post3")
@doc_api(req=dict, res=list)
def test_post3():  # type: ignore
    obj = get_json_values_from_req(("obj", SomeObj5))
    return obj.json()


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
