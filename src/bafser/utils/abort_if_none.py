from typing import TYPE_CHECKING

from flask import abort

if TYPE_CHECKING:
    from bafser import Undefined


def abort_if_none[T](value: T | None | type["Undefined"], name: str | None = None, msg: str = "%s not found", code: int = 404) -> T:
    from bafser import Undefined, response_msg

    value = Undefined.default(value)
    if value is None:
        if name is None:
            name = "item"
        if "%s" in msg:
            msg = (msg % name).capitalize()
        abort(response_msg(msg, code))

    return value
