from typing import Any

from flask import jsonify


def response_msg(msg: str, status_code: int = 200, *, code: str | None = None, details: Any = None):
    data: dict[str, Any] = {"msg": msg}
    if code is not None:
        data["code"] = code
    if details is not None:
        data["details"] = details
    res = jsonify(data)
    res.status_code = status_code
    return res
