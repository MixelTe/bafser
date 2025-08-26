from typing import Any
from flask import jsonify


def jsonify_list(items: list[Any], field_get_dict: str = "get_dict"):
    """
    calls `flask.jsonify` with all items called `field_get_dict` method

    If item is JsonObj then `.json()` will be called regardless of `field_get_dict` value
    """
    return jsonify([_getjson(x, field_get_dict) for x in items])


def _getjson(item: Any, f: str):
    from .. import JsonObj
    if isinstance(item, JsonObj):
        return item.json()
    return getattr(item, f)()
