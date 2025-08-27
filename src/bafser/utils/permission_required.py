from functools import wraps
from typing import Any, Callable, TypeVar, TYPE_CHECKING

from flask import abort
if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from .. import UserBase

TFn = TypeVar("TFn", bound=Callable[..., Any])


def create_permission_required_decorator(*, permission_desc: str | None = None) -> \
        Callable[[Callable[["Session", "UserBase", dict[str, Any]], bool]], Callable[[TFn], TFn]]:
    def creator(check_permission: Callable[["Session", "UserBase", dict[str, Any]], bool]):
        def wrapper(fn: TFn) -> TFn:
            @wraps(fn)
            def decorator(*args: Any, **kwargs: Any):
                if "db_sess" not in kwargs:
                    abort(500, "permission_required: no db_sess")
                if "user" not in kwargs:
                    abort(500, "permission_required: no user")

                if not check_permission(kwargs["db_sess"], kwargs["user"], kwargs):
                    abort(403)

                return fn(*args, **kwargs)
            decorator._doc_api_perms = permission_desc  # type: ignore
            return decorator  # type: ignore
        return wrapper
    return creator


def permission_required(*operations: tuple[str, str]):
    @create_permission_required_decorator(permission_desc=" && ".join(v[0] for v in operations))
    def check(db_sess: "Session", user: "UserBase", kwargs: dict[str, Any]):
        for operation in operations:
            if not user.check_permission(operation):
                return False

        return True
    return check


def permission_required_any(*operations: tuple[str, str]):
    @create_permission_required_decorator(permission_desc=" || ".join(v[0] for v in operations))
    def check(db_sess: "Session", user: "UserBase", kwargs: dict[str, Any]):
        for operation in operations:
            if user.check_permission(operation):
                return True

        return False
    return check
