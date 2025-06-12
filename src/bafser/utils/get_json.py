from flask import Request

is_json = bool


def get_json(request: Request) -> tuple[object, is_json]:
    if not request.is_json:
        return None, False
    try:
        json = request.get_json()
        return json, True
    except Exception:
        return None, False
