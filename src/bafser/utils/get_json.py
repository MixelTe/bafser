from typing import Any, TypeAlias

from flask import Request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

IsJson: TypeAlias = bool

_LIMIT_EXCEEDED_KEY = "bafser.json_body_limit_exceeded"


def get_json(request: Request) -> tuple[Any, IsJson]:
    if request.environ.get(_LIMIT_EXCEEDED_KEY):
        raise RequestEntityTooLarge()

    if not request.is_json:
        return None, False

    maximum = request.max_content_length
    if maximum is not None and request.content_length is None and request.environ.get("wsgi.input_terminated"):
        # Clear any pre-cached stream so get_data() wraps wsgi.input with the active limit.
        request.__dict__.pop("stream", None)
        data = request.get_data(cache=True)

        # LimitedStream stops at the cap without checking EOF. Read 1 extra byte to ensure
        # a valid truncated JSON prefix isn't mistakenly parsed as a complete payload.
        if len(data) > maximum or (len(data) == maximum and request.environ["wsgi.input"].read(1)):
            # The cached prefix may itself be valid JSON. Remember rejection so
            # another call cannot accept it after lookahead consumed the excess byte.
            request.environ[_LIMIT_EXCEEDED_KEY] = True
            raise RequestEntityTooLarge()

    # Werkzeug normalizes syntax errors; excessive nesting is a RecursionError
    # from Python's decoder and must also remain a client error.
    try:
        return request.get_json(), True
    except RecursionError:
        raise BadRequest() from None
