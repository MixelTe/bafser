from typing import Any
from flask import jsonify


def jsonify_list(items: list[Any], field_get_dict: str = "get_dict"):
    return jsonify(list(map(lambda x: getattr(x, field_get_dict)(), items)))
