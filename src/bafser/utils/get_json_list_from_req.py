from flask import abort, g

from . import response_msg


def get_json_list_from_req() -> list:
    values, is_json = g.json
    if not is_json:
        abort(response_msg("body is not json", 415))

    if not isinstance(values, list):
        abort(response_msg("body is not json list", 400))

    return values
