from flask import jsonify


def jsonify_list(items, field_get_dict="get_dict"):
    return jsonify(list(map(lambda x: getattr(x, field_get_dict)(), items)))
