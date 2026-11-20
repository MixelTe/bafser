from collections.abc import Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, TypeVar

from flask import abort
from flask_jwt_extended import get_jwt_identity, jwt_required  # pyright: ignore[reportUnknownVariableType]

from ..authentication import get_user_id_by_jwt_identity

if TYPE_CHECKING:
    from bafser import TOperation

TFn = TypeVar("TFn", bound=Callable[..., Any])


def protected_route(
    *,
    perms: "TOperation | list[TOperation] | None" = None,
    perms_any: "TOperation | list[TOperation] | None" = None,
    check_user: bool = False,
):
    """Require a valid JWT, optionally checking the current user and revocation.

    Permission checks always resolve the current user. Without permissions or
    check_user, validation is token-only and deliberately does not read the DB.
    """
    from bafser import UserBase

    if type(check_user) is not bool:
        raise TypeError("check_user must be bool")
    permission_desc = None
    if perms:
        if isinstance(perms, tuple):
            perms = [perms]
        permission_desc = " && ".join(v[0] for v in perms)
    if perms_any:
        if isinstance(perms_any, tuple):
            perms_any = [perms_any]
        desc = " || ".join(v[0] for v in perms_any)
        permission_desc = desc if not permission_desc else f"{permission_desc} && ({desc})"

    def decorator(fn: TFn, /) -> TFn:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any):
            if get_user_id_by_jwt_identity(get_jwt_identity()) is None:
                abort(401)
            if check_user or perms or perms_any:
                user = UserBase.current
                if perms and not user.has_permissions(perms):
                    abort(403)
                if perms_any and not user.has_any_permissions(perms_any):
                    abort(403)
            return fn(*args, **kwargs)

        wrapper._doc_api_jwt = True  # type: ignore
        wrapper._bafser_check_user = bool(check_user or perms or perms_any)  # type: ignore
        if permission_desc:
            wrapper._doc_api_perms = permission_desc  # type: ignore

        return jwt_required()(wrapper)

    return decorator
