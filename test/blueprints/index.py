from test.data import Operations
from test.data.img import ImageJson, Img
from test.data.user import User
from typing import Any, Literal, NotRequired, TypedDict

from flask import Blueprint, abort, jsonify, send_from_directory
from flask_jwt_extended import jwt_required, set_access_cookies  # type: ignore
from sqlalchemy.orm import Session

import bafser_config
from bafser import (JsonObj, JsonOpt, JsonSingleKey, Undefined, UserDict, create_access_token, doc_api, get_api_docs, get_app_config,
                    get_json_values_from_req, permission_required, render_docs_page, response_msg, use_db_session, use_user)

blueprint = Blueprint("index", __name__)


@blueprint.get("/api")
def docs():
    return get_api_docs()


@blueprint.get("/api/docs")
def docs_page():
    if not get_app_config().DEV_MODE:
        abort(404)
    return render_docs_page()


@blueprint.get("/")
def index():
    return send_from_directory(bafser_config.blueprints_folder, "index.html")


@blueprint.get("/api/user")
@doc_api(res=UserDict, desc="Get current user")
@jwt_required()
def user():
    return User.current.get_dict()


class LoginJson(JsonObj):
    login: str
    password: str


@blueprint.post("/api/auth")
@doc_api(req=LoginJson, res=UserDict, desc="Get auth cookie")
@use_db_session
def login(db_sess: Session):
    data = LoginJson.get_from_req()
    user = User.get_by_login(db_sess, data.login)

    if not user or not user.check_password(data.password):
        return response_msg("Неправильный логин или пароль", 400)

    response = jsonify(user.get_dict())
    access_token = create_access_token(user)
    set_access_cookies(response, access_token)
    return response


@blueprint.get("/api/item/<int:itemId>/<name>")
@doc_api(desc="Test params in url")
def item(itemId: int, name: str):  # type: ignore
    return {"itemId": itemId, "name": name}  # type: ignore


class SomeDict2(TypedDict):
    value: int
    isCool: NotRequired[bool]


class SomeDict1(TypedDict):
    name: str
    keys: list[int | str]
    v: list[SomeDict2]


@blueprint.post("/api/post")
def test_post():  # type: ignore
    a, b, c, d, e, f, g, h = get_json_values_from_req(("a", int), ("b", str, "def"), ("c", bool), ("d", list, []),
                                                      ("e", list[int], []), ("f", dict, {}), ("g", dict[str, int], {}), ("h", SomeDict1))
    return {"a": a, "b": b, "c": c, "d": d, "e": e, "f": f, "g": g, "h": h}  # type: ignore


class SomeObj2(JsonObj):
    value: int = 5
    isCool: JsonOpt[bool] = Undefined


class SomeObj(JsonObj):
    name: str = JsonObj.field(default="qq", desc="The name of obj")
    aa: Any
    keys: JsonOpt[list[int | str]] = Undefined
    v: list[list[SomeObj2]] = JsonObj.field(default_factory=lambda: [[SomeObj2()]])


class SomeDict(TypedDict):
    name: str
    keys: list[int | str]
    v: list[list[SomeObj2]]


class SomeObjRes(JsonObj):
    a: int
    objs: list[SomeObj]


@blueprint.post("/api/post2")
@doc_api(req=list[SomeObj], res=SomeObjRes, desc="The best route")
def test_post2():  # type: ignore
    # objs = get_json_list_from_req(SomeDict)
    objs = SomeObj.get_list_from_req()
    return SomeObjRes(a=1, objs=objs).json()


class SomeObj3(JsonObj):
    name: Literal["3"]
    v: int


class SomeObj4(JsonObj):
    name: Literal["4"]
    d: str


class SomeObj5(JsonObj):
    objs: list[SomeObj3 | SomeObj4]
    d: dict[str, "SomeObj5"]


@blueprint.post("/api/post3")
@doc_api(req=JsonSingleKey["obj", SomeObj5], res=SomeObj5)
def test_post3():  # type: ignore
    obj = SomeObj5.get_from_req("obj")
    return obj.json()


@blueprint.post("/api/post4")
@doc_api(req=SomeObj5, res=SomeObj5)
def test_post4():  # type: ignore
    obj = SomeObj5.get_from_req()
    return obj.json()


@blueprint.post("/api/img")
@doc_api(req=JsonSingleKey["img", ImageJson], res=JsonSingleKey["id", int])
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
