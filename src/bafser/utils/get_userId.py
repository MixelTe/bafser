from flask import abort, g
from flask_jwt_extended import unset_jwt_cookies  # type: ignore

from .response_msg import response_msg


def get_userId_required() -> int:
    userId = g.userId
    if userId is not None:
        return userId
    response = response_msg("The JWT has expired", 401)
    unset_jwt_cookies(response)
    abort(response)


def get_userId() -> int | None:
    return g.userId
