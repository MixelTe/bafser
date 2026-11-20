import hashlib
import hmac
import json
from typing import TYPE_CHECKING, Any, cast

from flask import current_app
from flask_jwt_extended import create_access_token as jwt_create_access_token  # type: ignore
from sqlalchemy import select
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from . import UserBase


_IDENTITY_VERSION = "bafser.auth.v1"
_STAMP_PURPOSE = b"bafser:jwt-password-stamp:v1\0"


def _password_stamp(user_id: int, password: str) -> str:
    """Bind a token to the current password without disclosing its stored hash."""
    secret: Any = current_app.config.get("JWT_SECRET_KEY")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    if isinstance(secret, str):
        secret = secret.encode("utf-8")
    if not isinstance(secret, bytes) or not secret.strip():
        raise RuntimeError("JWT_SECRET_KEY must contain a server-side secret")
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("An access token requires a persisted user ID")
    if not isinstance(password, str) or not password:  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError("An access token requires a stored password hash")
    message = json.dumps([user_id, password], ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(secret, _STAMP_PURPOSE + message, hashlib.sha256).hexdigest()


def create_access_token(user: "UserBase") -> str:
    """Create a signed token whose identity is invalidated by a password change."""
    identity = json.dumps([_IDENTITY_VERSION, user.id, _password_stamp(user.id, user.password)], separators=(",", ":"))
    return jwt_create_access_token(identity=identity)


def _parse_identity(jwt_identity: Any) -> tuple[int, str] | None:
    if not isinstance(jwt_identity, str):
        return None
    try:
        identity = json.loads(jwt_identity)
    except (TypeError, ValueError):
        return None
    if not isinstance(identity, list) or len(identity) != 3:  # pyright: ignore[reportUnknownArgumentType]
        return None
    version, user_id, stamp = cast(tuple[str, int, str], identity)
    if version != _IDENTITY_VERSION or type(user_id) is not int or user_id <= 0:
        return None
    if (
        not isinstance(stamp, str)  # pyright: ignore[reportUnnecessaryIsInstance]
        or len(stamp) != 64
        or any(char not in "0123456789abcdef" for char in stamp)
    ):
        return None
    return user_id, stamp


def get_user_id_by_jwt_identity(jwt_identity: Any) -> int | None:
    """Read an ID without I/O; the caller must first verify the JWT signature/expiry.

    This does not establish that the user still exists or the token is unrevoked.
    """
    identity = _parse_identity(jwt_identity)
    return None if identity is None else identity[0]


def get_user_by_jwt_identity(db_sess: Session, jwt_identity: Any, *, lazyload: bool = False, for_update: bool = False) -> "UserBase | None":
    """Verify stored authorization state independently of cached ORM attributes.

    Normal reads follow the caller's transaction isolation. for_update=True
    requests a locking current read and refreshes the ORM row through the model
    helper. Ordinary validation does not flush or overwrite pending ORM changes.
    """
    from .data.user import get_user_table

    identity = _parse_identity(jwt_identity)
    if identity is None:
        return None
    user_id, stamp = identity
    if not for_update:
        state = _get_authorization_state(db_sess, user_id)
        if state is None:
            return None
        password, deleted = state
        if deleted or not hmac.compare_digest(_password_stamp(user_id, password), stamp):
            return None
    with db_sess.no_autoflush:
        if lazyload:
            user = get_user_table().get_lazy(user_id, for_update=for_update, db_sess=db_sess)
        else:
            user = get_user_table().get(user_id, for_update=for_update, db_sess=db_sess)
    if user is None or user.deleted or user.id != user_id:
        return None
    if for_update and not hmac.compare_digest(_password_stamp(user_id, user.password), stamp):
        return None
    return user


def _get_authorization_state(db_sess: Session, user_id: int, *, for_update: bool = False) -> tuple[str, bool] | None:
    from .data.user import get_user_table

    User = get_user_table()
    statement = select(User.password, User.deleted).where(User.id == user_id)
    if for_update:
        statement = statement.with_for_update()
    row = db_sess.execute(statement, execution_options={"autoflush": False}).one_or_none()
    return None if row is None else (row.password, row.deleted)


def renew_access_token(db_sess: Session, jwt_identity: Any) -> str | None:
    """Renew only a verified identity matching a fresh read in the view's transaction.

    MySQL FOR UPDATE reads current state even after a REPEATABLE READ snapshot.
    The row lock lasts until the request transaction ends. Scalar columns and
    disabled autoflush preserve pending ORM changes and avoid an extra pooled
    connection while the view may still own the pool's only connection.
    """
    identity = _parse_identity(jwt_identity)
    if identity is None:
        return None
    user_id, stamp = identity
    state = _get_authorization_state(db_sess, user_id, for_update=True)
    if state is None:
        return None
    password, deleted = state
    if deleted:
        return None
    if not hmac.compare_digest(_password_stamp(user_id, password), stamp):
        return None
    return jwt_create_access_token(identity=jwt_identity)
