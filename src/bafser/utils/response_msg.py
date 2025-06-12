from flask import jsonify


def response_msg(msg: str, status_code: int = 200):
    res = jsonify({"msg": msg})
    res.status_code = status_code
    return res
