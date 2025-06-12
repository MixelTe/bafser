from typing import Any, Union
from flask import abort, g

from . import get_json_values, response_msg

field_name = str
default_value = Any


def get_json_values_from_req(*field_names: Union[field_name, tuple[field_name, default_value]]):
    data, is_json = g.json
    if not is_json:
        abort(response_msg("body is not json", 415))

    values, values_error = get_json_values(data, *field_names)

    if values_error:
        abort(response_msg(values_error, 400))

    return values
