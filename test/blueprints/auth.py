from test.data.user import User

from flask import Blueprint, jsonify
from flask_jwt_extended import set_access_cookies, unset_jwt_cookies  # pyright: ignore[reportUnknownVariableType]
from sqlalchemy.orm import Session

from bafser import JsonObj, UserDict, create_access_token, doc_api, response_msg, use_db_session

blueprint = Blueprint("auth", __name__)


class LoginJson(JsonObj):
    login: str
    password: str


@blueprint.post("/api/login")
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


@blueprint.post("/api/logout")
@doc_api(desc="Remove auth cookie")
def logout():
    response = response_msg("logout successful")
    unset_jwt_cookies(response)
    return response
