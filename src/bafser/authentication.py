from typing import Any
from flask_jwt_extended import create_access_token as jwt_create_access_token  # type: ignore
from sqlalchemy.orm import Session

from .data.user import get_user_table
from . import UserBase  # type: ignore


def create_access_token(user: UserBase):
    return jwt_create_access_token(identity=[user.id, user.password])


def get_user_id_by_jwt_identity(jwt_identity: Any):
    if not isinstance(jwt_identity, (list, tuple)) or len(jwt_identity) != 2:  # type: ignore
        return None
    id, password = jwt_identity  # type: ignore
    if not isinstance(id, int) or not isinstance(password, str):
        return None

    return id


def get_user_by_jwt_identity(db_sess: Session, jwt_identity: Any):
    if not isinstance(jwt_identity, (list, tuple)) or len(jwt_identity) != 2:  # type: ignore
        return None
    id, password = jwt_identity  # type: ignore
    if not isinstance(id, int) or not isinstance(password, str):
        return None

    user = get_user_table().get(db_sess, id)
    if not user:
        return None
    if user.password != jwt_identity[1]:
        return None
    return user
