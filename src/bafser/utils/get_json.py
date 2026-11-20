import re
from codecs import BOM_UTF16_BE, BOM_UTF16_LE, BOM_UTF32_BE, BOM_UTF32_LE
from typing import Any, TypeAlias

from flask import Request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge

IsJson: TypeAlias = bool

_LIMIT_EXCEEDED_KEY = "bafser.json_body_limit_exceeded"
_MAX_JSON_DEPTH = 256
_JSON_DEPTH_TOKENS = re.compile(rb'["\\{}\[\]]')


def _json_depth_scan_data(data: bytes) -> bytes:
    # The default JSON provider also accepts UTF-16 and UTF-32, with or without
    # a BOM. Decode those before looking for ASCII syntax at character boundaries.
    if data.startswith((BOM_UTF32_BE, BOM_UTF32_LE)):
        encoding = "utf-32"
    elif data.startswith((BOM_UTF16_BE, BOM_UTF16_LE)):
        encoding = "utf-16"
    elif data.startswith(b"\0\0"):
        encoding = "utf-32-be"
    elif data.startswith(b"\0"):
        encoding = "utf-16-be"
    elif data[1:4] == b"\0\0\0":
        encoding = "utf-32-le"
    elif data[1:2] == b"\0":
        encoding = "utf-16-le"
    else:
        return data
    return data.decode(encoding, errors="surrogatepass").encode("ascii", errors="replace")


def _check_json_depth(data: bytes) -> None:
    try:
        data = _json_depth_scan_data(data)
    except UnicodeDecodeError:
        # Let the JSON provider report invalid input through the usual handler.
        return

    depth = 0
    in_string = False
    escaped_at = -1
    for match in _JSON_DEPTH_TOKENS.finditer(data):
        token = match[0]
        if in_string:
            if match.start() == escaped_at:
                continue
            if token == b"\\":
                escaped_at = match.end()
            elif token == b'"':
                in_string = False
        elif token == b'"':
            in_string = True
        elif token in (b"[", b"{"):
            depth += 1
            if depth > _MAX_JSON_DEPTH:
                raise BadRequest()
        elif token in (b"]", b"}"):
            depth -= 1


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
    else:
        data = request.get_data(cache=True)

    _check_json_depth(data)

    # A decoder can still reach its own recursion limit within the depth cap.
    try:
        return request.get_json(), True
    except RecursionError:
        raise BadRequest() from None
