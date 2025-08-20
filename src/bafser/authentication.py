import json
from typing import TYPE_CHECKING, Any
from flask_jwt_extended import create_access_token as jwt_create_access_token  # type: ignore
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from . import UserBase


def create_access_token(user: "UserBase"):
    return jwt_create_access_token(identity=json.dumps([user.id, user.password]))


def get_user_id_by_jwt_identity(jwt_identity: Any):
    jwt_identity = json.loads(jwt_identity)
    if not isinstance(jwt_identity, list) or len(jwt_identity) != 2:  # type: ignore
        return None
    id, password = jwt_identity  # type: ignore
    if not isinstance(id, int) or not isinstance(password, str):
        return None

    return id


def get_user_by_jwt_identity(db_sess: Session, jwt_identity: Any, *, lazyload: bool = False, for_update: bool = False):
    from .data.user import get_user_table
    jwt_identity = json.loads(jwt_identity)
    if not isinstance(jwt_identity, list) or len(jwt_identity) != 2:  # type: ignore
        return None
    id, password = jwt_identity  # type: ignore
    if not isinstance(id, int) or not isinstance(password, str):
        return None

    if lazyload:
        user = get_user_table().get_lazy(db_sess, id, for_update=for_update)
    else:
        user = get_user_table().get(db_sess, id, for_update=for_update)
    if not user:
        return None
    if user.password != jwt_identity[1]:
        return None
    return user
