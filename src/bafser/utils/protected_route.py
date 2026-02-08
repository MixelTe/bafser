from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar

from flask import abort
from flask_jwt_extended import jwt_required  # pyright: ignore[reportUnknownVariableType]

if TYPE_CHECKING:
    from bafser import TOperation

    from .. import UserBase

TFn = TypeVar("TFn", bound=Callable[..., Any])


def protected_route(*, perms: "TOperation | list[TOperation] | None" = None, perms_any: "TOperation | list[TOperation] | None" = None):
    from bafser import UserBase

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
            if perms and not has_permissions(UserBase.current, perms):
                abort(403)
            if perms_any and not has_any_permissions(UserBase.current, perms_any):
                abort(403)
            return fn(*args, **kwargs)

        wrapper._doc_api_jwt = True  # type: ignore
        if permission_desc:
            wrapper._doc_api_perms = permission_desc  # type: ignore

        return jwt_required()(wrapper)

    return decorator


def has_permissions(user: "UserBase", operations: "list[TOperation]"):
    for operation in operations:
        if not user.check_permission(operation):
            return False
    return True


def has_any_permissions(user: "UserBase", operations: "list[TOperation]"):
    for operation in operations:
        if user.check_permission(operation):
            return True
    return False
